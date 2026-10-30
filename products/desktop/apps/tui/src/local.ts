import { getRemotePiConversation } from "@posthog/agent/pi/remote-rpc-client";
import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { PiRuntime } from "@posthog/agent/pi/runtime";
import type { AgentConversationEvent, StoredLogEntry } from "@posthog/shared";
import type { McpToolPolicyUpdater } from "@posthog/workspace-server/services/agent/ports";
import { controlOf, type PiControl } from "./models";
import { type AgentPrompt, type PromptReply, promptId } from "./prompts";
import { emptyRunView, type RunView } from "./runs";

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
  private readonly promptListeners = new Set<
    (prompts: AgentPrompt[]) => void
  >();

  constructor(
    private readonly client: PiRpcClient,
    private readonly policies: McpToolPolicyUpdater,
  ) {
    this.runtime = new PiRuntime(client);
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
    this.control = controlOf(client);
  }

  // Starts the agent and replays the conversation its session file already holds.
  async start(): Promise<void> {
    await this.client.start();
    const history = await getRemotePiConversation(this.client);
    this.publish({
      ...this.view,
      loaded: true,
      status: "in_progress",
      entries: [...history.map(asEntry), ...this.view.entries],
    });
  }

  watch(onView: (view: RunView) => void): () => void {
    this.listeners.add(onView);
    if (this.view.loaded) onView(this.view);
    return () => this.listeners.delete(onView);
  }

  // A message sent mid-turn waits for the turn to finish.
  async prompt(message: string): Promise<void> {
    const response = await this.runtime.sendCommand({
      type: "prompt",
      id: globalThis.crypto.randomUUID(),
      message,
      streamingBehavior: "followUp",
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
