import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { RequestPermissionRequest } from "@agentclientprotocol/sdk";
import type { AcpMessage, StoredLogEntry } from "@posthog/shared";
import type { AgentService } from "@posthog/workspace-server/services/agent/agent";
import { AgentServiceEvent } from "@posthog/workspace-server/services/agent/schemas";
import type { LocalAgent } from "./local";
import type { AcpLog } from "./localChats";
import type { PiControl } from "./models";
import { type AgentPrompt, type PromptReply, promptId } from "./prompts";
import { emptyRunView, type RunView } from "./runs";

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

const NOT_ON_CLAUDE = "Not available on a Claude Code chat";
const unavailable = (): Promise<never> =>
  Promise.reject(new Error(NOT_ON_CLAUDE));

// Claude Code running on this machine on the user's own Claude plan, through the desktop app's agent service.
export class ClaudeLocalSession implements LocalAgent {
  readonly runtime = "acp";
  readonly plan = true;
  readonly control: PiControl;
  private sessionId: string | null = null;
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
      bash: unavailable,
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
      this.setPrompts([
        ...this.prompts,
        {
          kind: "acp",
          request: {
            taskRunId: request.taskRunId,
            toolCallId: request.toolCall.toolCallId,
            title: request.toolCall.title ?? "Allow this tool call?",
            options: request.options,
          },
        },
      ]);
    };
    const saved = this.log?.load();
    if (saved?.entries.length)
      this.publish({ ...this.view, entries: saved.entries });
    this.agent.on(AgentServiceEvent.SessionEvent, onEvent);
    this.agent.on(AgentServiceEvent.PermissionRequest, onPermission);
    this.unsubscribe.push(
      () => this.agent.off(AgentServiceEvent.SessionEvent, onEvent),
      () => this.agent.off(AgentServiceEvent.PermissionRequest, onPermission),
    );
    const params = {
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
    // A remembered session resumes where it left off; one Claude no longer has starts over, keeping the log shown.
    const resumed = saved?.sessionId
      ? await this.agent
          .reconnectSession({ ...params, sessionId: saved.sessionId })
          .catch(() => null)
      : null;
    const { sessionId, configOptions } =
      resumed ??
      (await this.agent.startSession({ ...params, runMode: "local" }));
    this.sessionId = sessionId;
    this.configOptions = configOptions;
    this.publish({
      ...this.view,
      loaded: true,
      local: true,
      status: "in_progress",
    });
  }

  watch(onView: (view: RunView) => void): () => void {
    this.listeners.add(onView);
    if (this.view.loaded) onView(this.view);
    return () => this.listeners.delete(onView);
  }

  // A message sent mid-turn steers it; the first message of a turn waits for the turn to end.
  async prompt(message: string): Promise<void> {
    if (!this.sessionId) throw new Error("The agent has not started");
    const steer = this.turn !== null;
    const sent = this.agent.prompt(
      this.sessionId,
      [{ type: "text", text: message }],
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
