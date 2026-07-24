import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import type { AgentConversationEvent } from "@posthog/shared";
import {
  createPiConversationTranslator,
  type PiConversationTranslator,
} from "./conversation/translatePiConversation";
import {
  createPiRpcClient,
  getAvailableModelsWithThinkingLevels,
  getPiRpcClientProcess,
  type PiRpcClient,
  type PiRpcClientOptions,
} from "./rpc-client";
import type { PiModelOption } from "./types";

export class PiRuntime {
  readonly client: PiRpcClient;

  private readonly translator: PiConversationTranslator;
  private readonly runtimeListeners = new Set<
    (event: AgentSessionEvent) => void
  >();
  private readonly conversationListeners = new Set<
    (event: AgentConversationEvent) => void
  >();

  constructor(client: PiRpcClient) {
    this.client = client;
    this.translator = createPiConversationTranslator();
    client.onEvent((event) => this.handleEvent(event));
  }

  get process() {
    return getPiRpcClientProcess(this.client);
  }

  onRuntimeEvent(listener: (event: AgentSessionEvent) => void): () => void {
    this.runtimeListeners.add(listener);
    return () => this.runtimeListeners.delete(listener);
  }

  onConversationEvent(
    listener: (event: AgentConversationEvent) => void,
  ): () => void {
    this.conversationListeners.add(listener);
    return () => this.conversationListeners.delete(listener);
  }

  availableModels(): Promise<PiModelOption[]> {
    return getAvailableModelsWithThinkingLevels(this.client);
  }

  async conversation(): Promise<AgentConversationEvent[]> {
    const entries = await this.client.getEntries();
    const translator = createPiConversationTranslator();
    const events: AgentConversationEvent[] = [];

    for (const entry of entries.entries) {
      if (entry.type === "message") {
        events.push(...translator.translateHistoryMessage(entry.message));
      }
    }

    return events;
  }

  private handleEvent(event: AgentSessionEvent): void {
    for (const listener of this.runtimeListeners) {
      listener(event);
    }

    const conversationEvents = this.translator.translateEvent(event);
    for (const conversationEvent of conversationEvents) {
      for (const listener of this.conversationListeners) {
        listener(conversationEvent);
      }
    }
  }
}

export function createPiRuntime(options: PiRpcClientOptions): PiRuntime {
  return new PiRuntime(createPiRpcClient(options));
}
