import type { Readable } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import type { SDKStartupFailureReason } from "@anthropic-ai/claude-agent-sdk";
import type { StartupFailure } from "@posthog/agent-contracts/startup-failure";
import { z } from "zod";

export type InitializationPhase = "sdk_initialization" | "setup_hooks";

export interface CliOutputSummary {
  lines: number;
  hasPartialLine: boolean;
  msSinceLastLine: number | null;
  lastMessageType: string | null;
}

type InitializationResult<Value> =
  | { result: "success"; value: Value }
  | {
      result: "timeout";
      phase: InitializationPhase;
      timeoutMs: number;
      cliOutput: CliOutputSummary;
    };

const MAX_OBSERVED_LINE_LENGTH = 256 * 1024;
const MAX_MESSAGE_TYPE_LENGTH = 100;

const startupRetryability = {
  org_pin_api_key_conflict: "requires_action",
  org_verify_failed: "unknown",
  org_pin_mismatch: "requires_action",
  managed_settings_invalid: "requires_action",
  remote_settings_required_unavailable: "unknown",
  gateway_signin_required: "requires_action",
  gateway_access_denied: "requires_action",
  proxy_invalid: "requires_action",
  temp_dir_unusable: "unknown",
  cwd_unavailable: "unknown",
  shell_tool_missing: "requires_action",
  session_held_by_background: "transient",
  worktree_resume_refused: "unknown",
  worktree_unverified: "transient",
  cli_version_too_old: "requires_action",
  bypass_root: "requires_action",
  sandbox_required_unavailable: "requires_action",
  provider_not_allowed: "requires_action",
  org_config_required_unavailable: "unknown",
  org_config_refused: "requires_action",
} satisfies Record<SDKStartupFailureReason, StartupFailure["retryability"]>;

const startupResultSchema = z.object({
  type: z.literal("result"),
  subtype: z.literal("error_during_execution"),
  startup_failure_reason: z.enum(
    Object.keys(startupRetryability) as [
      SDKStartupFailureReason,
      ...SDKStartupFailureReason[],
    ],
  ),
});

export class SessionInitialization {
  private activeHooks = new Set<string>();
  private hooksStartedAt: number | undefined;
  private outputLines = 0;
  private hasPartialLine = false;
  private lastLineAt: number | undefined;
  private lastMessageType: string | null = null;
  private reschedule: (() => void) | undefined;
  private detach: (() => void) | undefined;
  private disposed = false;
  private failureReason: SDKStartupFailureReason | null = null;

  constructor(
    private onPhaseChange: (phase: InitializationPhase) => void,
    private connectionTimeoutMs = 30_000,
    private hooksTimeoutMs = 600_000,
  ) {}

  get phase(): InitializationPhase {
    return this.activeHooks.size > 0 ? "setup_hooks" : "sdk_initialization";
  }

  get failure(): StartupFailure {
    return {
      provider: "claude",
      phase: this.phase,
      reason: this.failureReason,
      retryability: this.failureReason
        ? startupRetryability[this.failureReason]
        : "unknown",
    };
  }

  get timeoutMs(): number {
    return this.phase === "setup_hooks"
      ? this.hooksTimeoutMs
      : this.connectionTimeoutMs;
  }

  observe(stdout: Readable): void {
    if (this.disposed) return;
    const decoder = new StringDecoder("utf8");
    let buffer = "";
    let oversized = false;
    const onData = (chunk: Buffer): void => {
      const parts = decoder.write(chunk).split("\n");
      for (let index = 0; index < parts.length; index++) {
        const part = parts[index];
        if (buffer.length + part.length > MAX_OBSERVED_LINE_LENGTH) {
          oversized = true;
          buffer = "";
        }
        if (!oversized) buffer += part;
        if (index < parts.length - 1) {
          this.outputLines++;
          this.lastLineAt = Date.now();
          if (!oversized) this.observeLine(buffer);
          buffer = "";
          oversized = false;
        }
      }
      this.hasPartialLine = oversized || buffer.length > 0;
    };
    stdout.on("data", onData);
    this.detach = () => stdout.off("data", onData);
  }

  private observeLine(line: string): void {
    let message: unknown;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    const startupResult = startupResultSchema.safeParse(message);
    if (startupResult.success) {
      this.failureReason = startupResult.data.startup_failure_reason;
    }
    if (
      message &&
      typeof message === "object" &&
      "type" in message &&
      typeof message.type === "string"
    ) {
      const messageType =
        "subtype" in message && typeof message.subtype === "string"
          ? `${message.type}/${message.subtype}`
          : message.type;
      this.lastMessageType = messageType.slice(0, MAX_MESSAGE_TYPE_LENGTH);
    }
    if (
      !message ||
      typeof message !== "object" ||
      !("type" in message) ||
      message.type !== "system" ||
      !("hook_event" in message) ||
      message.hook_event !== "SessionStart" ||
      !("hook_id" in message) ||
      typeof message.hook_id !== "string" ||
      !("subtype" in message)
    ) {
      return;
    }
    const previousPhase = this.phase;
    if (message.subtype === "hook_started") {
      this.activeHooks.add(message.hook_id);
      this.hooksStartedAt ??= Date.now();
    } else if (message.subtype === "hook_response") {
      this.activeHooks.delete(message.hook_id);
    }
    if (this.phase !== previousPhase) {
      this.onPhaseChange(this.phase);
      this.reschedule?.();
    }
  }

  private cliOutput(): CliOutputSummary {
    return {
      lines: this.outputLines,
      hasPartialLine: this.hasPartialLine,
      msSinceLastLine:
        this.lastLineAt === undefined ? null : Date.now() - this.lastLineAt,
      lastMessageType: this.lastMessageType,
    };
  }

  async wait<Value>(
    initialization: Promise<Value>,
  ): Promise<InitializationResult<Value>> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await new Promise<InitializationResult<Value>>(
        (resolve, reject) => {
          this.reschedule = () => {
            clearTimeout(timer);
            const phase = this.phase;
            const timeoutMs = this.timeoutMs;
            const remainingMs =
              phase === "setup_hooks"
                ? timeoutMs - (Date.now() - (this.hooksStartedAt ?? Date.now()))
                : timeoutMs;
            timer = setTimeout(
              () =>
                resolve({
                  result: "timeout",
                  phase,
                  timeoutMs,
                  cliOutput: this.cliOutput(),
                }),
              Math.max(0, remainingMs),
            );
          };
          this.reschedule();
          initialization.then(
            (value) => resolve({ result: "success", value }),
            reject,
          );
        },
      );
    } finally {
      clearTimeout(timer);
      this.reschedule = undefined;
      this.disposed = true;
      this.detach?.();
    }
  }
}
