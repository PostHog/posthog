import { execFile } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import type { RequestPermissionRequest } from "@agentclientprotocol/sdk";
import type { ImageContent } from "@earendil-works/pi-ai";
import type { AcpMessage, StoredLogEntry } from "@posthog/shared";
import type { AgentService } from "@posthog/workspace-server/services/agent/agent";
import {
  AgentServiceEvent,
  type StartSessionInput,
} from "@posthog/workspace-server/services/agent/schemas";
import type { LocalAgent } from "./local";
import type { AcpLog } from "./localChats";
import type { PiControl } from "./models";
import {
  type AcpQuestion,
  type AgentPrompt,
  type PromptReply,
  promptId,
} from "./prompts";
import { emptyRunView, type RunView } from "./runs";
import { type ShellResult, shellMessage } from "./shell";
import { claudeSettings } from "./starting";

export interface ClaudeLocalInput {
  taskId: string;
  taskRunId: string;
  cwd: string;
  apiHost: string;
  projectId: number;
  model?: string;
  effort?: string;
  // Claude Code's permission mode to start in.
  mode?: string;
}

type Choice = { value: string; name: string };
type ConfigOptions = Awaited<
  ReturnType<AgentService["startSession"]>
>["configOptions"];

const capitalised = (word: string): string =>
  word.charAt(0).toUpperCase() + word.slice(1);

// The plan Claude Code is signed in on ("Claude Max"), from its account file; "Claude plan" when that says nothing.
export function claudePlan(
  path: string = join(homedir(), ".claude.json"),
): string {
  try {
    const { oauthAccount } = JSON.parse(readFileSync(path, "utf8")) as {
      oauthAccount?: { organizationType?: string };
    };
    const tier = oauthAccount?.organizationType?.replace(/^claude_/, "");
    return tier ? `Claude ${capitalised(tier)}` : "Claude plan";
  } catch {
    return "Claude plan";
  }
}

// The model the agent service opened a session on, from its logged `session/new` request.
export const sessionModel = (entry: StoredLogEntry): string | undefined => {
  const { notification } = entry as {
    notification?: { method?: string; params?: { _meta?: { model?: string } } };
  };
  return notification?.method === "session/new"
    ? notification.params?._meta?.model
    : undefined;
};

const NOT_ON_CLAUDE = "Not available on a Claude Code chat";
const unavailable = (): Promise<never> =>
  Promise.reject(new Error(NOT_ON_CLAUDE));

// Claude Code running on this machine on the user's own Claude plan, through the desktop app's agent service.
export class ClaudeLocalSession implements LocalAgent {
  readonly runtime = "acp";
  readonly plan = true;
  readonly control: PiControl;
  // Claude Code reports no model over ACP, but the agent service logs the one it resolved when it opens the session.
  model: string | undefined;
  private sessionId: string | null = null;
  private params: Omit<StartSessionInput, "runMode"> | null = null;
  private configOptions: ConfigOptions;
  private turn: Promise<unknown> | null = null;
  private readonly listeners = new Set<(view: RunView) => void>();
  private view: RunView = emptyRunView;
  private prompts: AgentPrompt[] = [];
  private readonly promptListeners = new Set<
    (prompts: AgentPrompt[]) => void
  >();
  private readonly unsubscribe: (() => void)[] = [];

  constructor(
    private readonly agent: AgentService,
    private readonly input: ClaudeLocalInput,
    private readonly loggedIn: () => Promise<boolean>,
    private readonly log?: Pick<AcpLog, "load" | "append" | "session">,
  ) {
    this.model = input.model ?? claudeSettings().model;
    this.control = {
      models: unavailable,
      setModel: unavailable,
      efforts: unavailable,
      setEffort: unavailable,
      commands: async () => [],
      abort: async () => {
        if (this.sessionId) await this.agent.cancelPrompt(this.sessionId);
      },
      compact: unavailable,
      bash: (command) => this.bash(command),
      modes: async () => {
        const option = this.modeOption();
        return {
          available: (option.options as (Choice | { options: Choice[] })[])
            .flatMap((entry) => ("options" in entry ? entry.options : [entry]))
            .map(({ value, name }) => ({ id: value, name })),
          current: option.currentValue,
        };
      },
      setMode: async (id) => {
        if (!this.sessionId) throw new Error("The agent has not started");
        const option = this.modeOption();
        await this.agent.setSessionConfigOption(this.sessionId, option.id, id);
        option.currentValue = id;
      },
    };
  }

  // The agent service falls back to the gateway when Claude Code is logged out, which would bill PostHog.
  async start(): Promise<void> {
    if (!(await this.loggedIn()))
      throw new Error(
        "Log in to Claude Code first: run `claude auth login` in a terminal",
      );
    const onEvent = ({
      taskRunId,
      payload,
    }: {
      taskRunId: string;
      payload: unknown;
    }): void => {
      if (taskRunId !== this.input.taskRunId) return;
      const message = payload as AcpMessage;
      const entry = {
        type: "acp_message",
        timestamp: new Date(message.ts).toISOString(),
        notification: message.message,
      } as StoredLogEntry;
      this.log?.append(entry);
      this.model = sessionModel(entry) ?? this.model;
      // Claude names its own session once the SDK is up; a reopen resumes that session.
      const notification = message.message as {
        method?: string;
        params?: { sessionId?: string };
      };
      if (
        notification.method === "_posthog/sdk_session" &&
        notification.params?.sessionId
      )
        this.log?.session(notification.params.sessionId);
      this.publish({ ...this.view, entries: [...this.view.entries, entry] });
    };
    const onPermission = (
      request: Omit<RequestPermissionRequest, "sessionId"> & {
        taskRunId: string;
      },
    ): void => {
      if (request.taskRunId !== this.input.taskRunId) return;
      const meta = request.toolCall._meta as
        | { codeToolKind?: string; questions?: AcpQuestion[] }
        | undefined;
      const questions =
        meta?.codeToolKind === "question" && Array.isArray(meta.questions)
          ? meta.questions
          : undefined;
      this.setPrompts([
        ...this.prompts,
        {
          kind: "acp",
          request: {
            taskRunId: request.taskRunId,
            toolCallId: request.toolCall.toolCallId,
            title: request.toolCall.title ?? "Allow this tool call?",
            options: request.options,
            ...(questions && { questions }),
          },
        },
      ]);
    };
    // The agent service drops a session idle for 15 minutes; the next message reconnects it.
    const onIdleKilled = ({ taskRunId }: { taskRunId: string }): void => {
      if (taskRunId === this.input.taskRunId) this.sessionId = null;
    };
    const saved = this.log?.load();
    if (saved?.entries.length) {
      this.model = saved.entries.reduce<string | undefined>(
        (model, entry) => sessionModel(entry) ?? model,
        this.model,
      );
      this.publish({ ...this.view, entries: saved.entries });
    }
    this.agent.on(AgentServiceEvent.SessionEvent, onEvent);
    this.agent.on(AgentServiceEvent.PermissionRequest, onPermission);
    this.agent.on(AgentServiceEvent.SessionIdleKilled, onIdleKilled);
    this.unsubscribe.push(
      () => this.agent.off(AgentServiceEvent.SessionEvent, onEvent),
      () => this.agent.off(AgentServiceEvent.PermissionRequest, onPermission),
      () => this.agent.off(AgentServiceEvent.SessionIdleKilled, onIdleKilled),
    );
    this.params = {
      taskId: this.input.taskId,
      taskRunId: this.input.taskRunId,
      repoPath: this.input.cwd,
      apiHost: this.input.apiHost,
      projectId: this.input.projectId,
      adapter: "claude" as const,
      claudeModelAccess: "own-subscription" as const,
      permissionMode: this.input.mode ?? "auto",
      ...(this.input.model && { model: this.input.model }),
      ...(this.input.effort && {
        effort: this.input.effort as
          | "low"
          | "medium"
          | "high"
          | "xhigh"
          | "max",
      }),
    };
    await this.connect();
    this.publish({
      ...this.view,
      loaded: true,
      local: true,
      status: "in_progress",
    });
  }

  // A remembered session resumes where it left off; one Claude no longer has starts over, keeping the log shown.
  private async connect(): Promise<string> {
    if (!this.params) throw new Error("The agent has not started");
    const params = this.params;
    const remembered = this.log?.load().sessionId;
    const resumed = remembered
      ? await this.agent
          .reconnectSession({ ...params, sessionId: remembered })
          .catch(() => null)
      : null;
    const { sessionId, configOptions } =
      resumed ??
      // A TUI local chat has a task row but no run, so there is nothing on the server for its log to append to.
      (await this.agent.startSession({
        ...params,
        runMode: "local",
        skipLogPersistence: true,
      }));
    this.sessionId = sessionId;
    this.configOptions = configOptions;
    return sessionId;
  }

  watch(onView: (view: RunView) => void): () => void {
    this.listeners.add(onView);
    if (this.view.loaded) onView(this.view);
    return () => this.listeners.delete(onView);
  }

  // A message sent mid-turn steers it; the first message of a turn waits for the turn to end.
  // Claude Code has no shell RPC, so a ! command runs here, in the chat's folder, logged as the desktop app logs its
  // own user shell execute so the chat shows it like any other, then goes to the agent as a message.
  private async bash(command: string): Promise<ShellResult> {
    const id = `shell-${globalThis.crypto.randomUUID()}`;
    const log = (result?: {
      stdout: string;
      stderr: string;
      exitCode: number;
    }) =>
      this.record({
        type: "acp_message",
        timestamp: new Date().toISOString(),
        notification: {
          method: "_array/user_shell_execute",
          params: { id, command, cwd: this.input.cwd, result },
        },
      } as StoredLogEntry);
    log();
    let stdout = "";
    let stderr = "";
    let exitCode = 0;
    try {
      const run = await promisify(execFile)("sh", ["-c", command], {
        cwd: this.input.cwd,
        maxBuffer: 4 * 1024 * 1024,
      });
      stdout = run.stdout;
      stderr = run.stderr;
    } catch (error) {
      const failed = error as {
        stdout?: string;
        stderr?: string;
        code?: number;
      };
      stdout = failed.stdout ?? "";
      stderr = failed.stderr ?? String(error);
      exitCode = typeof failed.code === "number" ? failed.code : 1;
    }
    log({ stdout: stdout.trimEnd(), stderr: stderr.trimEnd(), exitCode });
    const output = stdout.trimEnd() || stderr.trimEnd();
    await this.prompt(shellMessage(command, output));
    return { output, exitCode, cancelled: false };
  }

  private record(entry: StoredLogEntry): void {
    this.log?.append(entry);
    this.publish({ ...this.view, entries: [...this.view.entries, entry] });
  }

  async prompt(message: string, images: ImageContent[] = []): Promise<void> {
    const sessionId = this.sessionId ?? (await this.connect());
    const steer = this.turn !== null;
    const sent = this.agent.prompt(
      sessionId,
      [
        { type: "text", text: message },
        ...images.map(({ data, mimeType }) => ({
          type: "image" as const,
          data,
          mimeType,
        })),
      ],
      { steer },
    );
    if (steer) {
      await sent;
      return;
    }
    this.turn = sent;
    try {
      await sent;
    } finally {
      if (this.turn === sent) this.turn = null;
    }
  }

  watchPrompts(onPrompts: (prompts: AgentPrompt[]) => void): () => void {
    this.promptListeners.add(onPrompts);
    onPrompts(this.prompts);
    return () => this.promptListeners.delete(onPrompts);
  }

  async answer(prompt: AgentPrompt, reply: PromptReply): Promise<void> {
    this.setPrompts(
      this.prompts.filter((open) => promptId(open) !== promptId(prompt)),
    );
    if (reply.kind !== "acp") return;
    this.agent.respondToPermission(
      reply.taskRunId,
      reply.toolCallId,
      reply.optionId,
      reply.customInput,
      reply.answers,
    );
  }

  async stop(): Promise<void> {
    for (const off of this.unsubscribe.splice(0)) off();
    if (this.sessionId) await this.agent.cancelSession(this.sessionId);
    this.publish({ ...this.view, status: "completed" });
  }

  private modeOption() {
    const option = this.configOptions?.find(
      (candidate) => candidate.id === "mode" && candidate.type === "select",
    );
    if (!option || option.type !== "select")
      throw new Error("This chat has no modes");
    return option;
  }

  private setPrompts(prompts: AgentPrompt[]): void {
    this.prompts = prompts;
    for (const listener of this.promptListeners) listener(prompts);
  }

  private publish(view: RunView): void {
    this.view = view;
    for (const listener of this.listeners) listener(view);
  }
}
