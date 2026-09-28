import type { Readable } from "node:stream";
import { StringDecoder } from "node:string_decoder";

type InitializationPhase = "sdk_initialization" | "setup_hooks";

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

  constructor(
    private onPhaseChange: (phase: InitializationPhase) => void,
    private connectionTimeoutMs = 30_000,
    private hooksTimeoutMs = 600_000,
  ) {}

  get phase(): InitializationPhase {
    return this.activeHooks.size > 0 ? "setup_hooks" : "sdk_initialization";
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
