import { getRemotePiConversation } from "@posthog/agent/pi/remote-rpc-client";
import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { PiRuntime } from "@posthog/agent/pi/runtime";
import type { AgentConversationEvent, StoredLogEntry } from "@posthog/shared";
import { controlOf, type PiControl } from "./models";
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

  constructor(private readonly client: PiRpcClient) {
    this.runtime = new PiRuntime(client);
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

  async stop(): Promise<void> {
    await this.client.stop();
    this.publish({ ...this.view, status: "completed" });
  }

  private publish(view: RunView): void {
    this.view = view;
    for (const listener of this.listeners) listener(view);
  }
}
