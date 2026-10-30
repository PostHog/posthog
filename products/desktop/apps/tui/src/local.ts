import type { ImageContent } from "@earendil-works/pi-ai";
import { getRemotePiConversation } from "@posthog/agent/pi/remote-rpc-client";
import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { PiRuntime } from "@posthog/agent/pi/runtime";
import type { AgentConversationEvent, StoredLogEntry } from "@posthog/shared";
import type { McpToolPolicyUpdater } from "@posthog/workspace-server/services/agent/ports";
import { controlOf, type PiControl } from "./models";
import { type AgentPrompt, type PromptReply, promptId } from "./prompts";
import { emptyRunView, type RunView } from "./runs";
import type { ShellResult } from "./shell";

// Local chats reuse the cloud transcript path, which reads pi events from log entries.
const asEntry = (event: AgentConversationEvent): StoredLogEntry => ({
  type: "pi_event",
  event,
});

// A pi agent running on this machine through the PostHog harness, shown like a cloud run.
export class LocalSession {
  readonly control: PiControl;
  private readonly runtime: PiRuntime;
  private readonly listeners = new Set<(view: RunView) => void>();
  private view: RunView = emptyRunView;
  private prompts: AgentPrompt[] = [];
  // The model's context window; turn usage carries it, so the composer can show how full the context is.
  private contextWindow: number | undefined;
  private readonly promptListeners = new Set<
    (prompts: AgentPrompt[]) => void
  >();

  constructor(
    private readonly client: PiRpcClient,
    private readonly policies: McpToolPolicyUpdater,
  ) {
    this.runtime = new PiRuntime(client, () => this.contextWindow);
    this.runtime.onExtensionEvent((event) => {
      if (event.type !== "extension_ui_request") return;
      if (
        event.method !== "select" &&
        event.method !== "confirm" &&
        event.method !== "input" &&
        event.method !== "editor"
      )
        return;
      this.setPrompts([...this.prompts, { kind: "dialog", request: event }]);
      // pi gives up on a timed prompt by itself, so the sheet goes with it.
      if ("timeout" in event && event.timeout)
        setTimeout(() => this.drop(event.id), event.timeout);
    });
    client.onMcpToolPermissionRequest((request) =>
      this.setPrompts([...this.prompts, { kind: "permission", request }]),
    );
    this.runtime.onConversationEvent((event) =>
      this.publish({
        ...this.view,
        entries: [...this.view.entries, asEntry(event)],
      }),
    );
    const control = controlOf(client, (command) => this.bash(command));
    this.control = {
      ...control,
      setModel: async (model) => {
        await control.setModel(model);
        await this.refreshContextWindow();
      },
    };
  }

  // Without a window the composer hides its donut, so a failed read costs nothing else.
  private async refreshContextWindow(): Promise<void> {
    try {
      const { model } = await this.client.getState();
      this.contextWindow = model?.contextWindow;
    } catch {}
  }

  // The runtime emits the command's conversation events itself, so the chat shows it like any other entry.
  private async bash(command: string): Promise<ShellResult> {
    const response = await this.runtime.sendCommand({
      type: "bash",
      id: globalThis.crypto.randomUUID(),
      command,
    });
    if (!response.success) throw new Error(response.error);
    return (
      (response as { data?: ShellResult }).data ?? {
        output: "",
        exitCode: undefined,
        cancelled: false,
      }
    );
  }

  // Starts the agent and replays the conversation its session file already holds.
  async start(): Promise<void> {
    await this.client.start();
    await this.refreshContextWindow();
    const history = await getRemotePiConversation(this.client);
    this.publish({
      ...this.view,
      loaded: true,
      local: true,
      status: "in_progress",
      entries: [...history.map(asEntry), ...this.view.entries],
    });
  }

  watch(onView: (view: RunView) => void): () => void {
    this.listeners.add(onView);
    if (this.view.loaded) onView(this.view);
    return () => this.listeners.delete(onView);
  }

  // A message sent mid-turn steers it: the agent reads it after its current tool calls, before its next step.
  async prompt(message: string, images: ImageContent[] = []): Promise<void> {
    const response = await this.runtime.sendCommand({
      type: "prompt",
      id: globalThis.crypto.randomUUID(),
      message,
      ...(images.length > 0 && { images }),
      streamingBehavior: "steer",
    });
    if (!response.success) throw new Error(response.error);
  }

  // Prompts come in order and stay until answered, so a chat opened later still shows them.
  watchPrompts(onPrompts: (prompts: AgentPrompt[]) => void): () => void {
    this.promptListeners.add(onPrompts);
    onPrompts(this.prompts);
    return () => this.promptListeners.delete(onPrompts);
  }

  async answer(prompt: AgentPrompt, reply: PromptReply): Promise<void> {
    this.drop(promptId(prompt));
    if (reply.kind === "dialog") {
      await this.client.respondToExtensionUI(reply.response);
      return;
    }
    if (reply.decision === "allow_always" && prompt.kind === "permission")
      await this.policies.approveMcpTool(
        prompt.request.installationId,
        prompt.request.toolName,
      );
    this.client.respondMcpToolPermission(reply.requestId, reply.decision);
  }

  private drop(id: string): void {
    this.setPrompts(this.prompts.filter((prompt) => promptId(prompt) !== id));
  }

  private setPrompts(prompts: AgentPrompt[]): void {
    this.prompts = prompts;
    for (const listener of this.promptListeners) listener(prompts);
  }

  async stop(): Promise<void> {
    await this.client.stop();
    this.publish({ ...this.view, status: "completed" });
  }

  private publish(view: RunView): void {
    this.view = view;
    for (const listener of this.listeners) listener(view);
  }
}

// Started local agents by task id. Kept on globalThis because a hot swap of src/ re-runs this module,
// and an agent that edits the TUI's own code must not stop itself.
const hotSwapSafe = globalThis as {
  __posthogTuiLocals?: Map<string, Promise<LocalSession>>;
};
hotSwapSafe.__posthogTuiLocals ??= new Map();
export const runningLocals = hotSwapSafe.__posthogTuiLocals;

export const stopLocals = async (): Promise<void> => {
  await Promise.allSettled(
    [...runningLocals.values()].map((started) =>
      started.then((local) => local.stop()),
    ),
  );
};
