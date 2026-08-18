import type {
  JsonAgentSessionEvent,
  RpcCommand,
  RpcResponse,
} from "@earendil-works/pi-coding-agent";
import type { AgentConversationEvent } from "@posthog/shared";
import {
  createPiConversationTranslator,
  type PiConversationTranslator,
  type PiDirectBashResult,
} from "./conversation/translatePiConversation";
import { getPiRpcClientProcess, type PiRpcClient } from "./rpc-client";
import { sendPiRpcCommand } from "./rpc-transport";
import type { PiExtensionEvent } from "./types";

export class PiRuntime {
  readonly client: PiRpcClient;

  private readonly translator: PiConversationTranslator;
  private readonly runtimeListeners = new Set<
    (event: JsonAgentSessionEvent) => void
  >();
  private readonly conversationListeners = new Set<
    (event: AgentConversationEvent) => void
  >();
  private readonly extensionListeners = new Set<
    (event: PiExtensionEvent) => void
  >();
  private readonly pendingUserMessages: Array<{
    id: string;
    message: string;
    type: "prompt" | "steer" | "follow_up";
  }> = [];
  private directBashActive = false;

  constructor(client: PiRpcClient) {
    this.client = client;
    this.translator = createPiConversationTranslator();
    client.onEvent((event) => this.handleEvent(event));
  }

  get process() {
    return getPiRpcClientProcess(this.client);
  }

  onRuntimeEvent(listener: (event: JsonAgentSessionEvent) => void): () => void {
    this.runtimeListeners.add(listener);
    return () => this.runtimeListeners.delete(listener);
  }

  onConversationEvent(
    listener: (event: AgentConversationEvent) => void,
  ): () => void {
    this.conversationListeners.add(listener);
    return () => this.conversationListeners.delete(listener);
  }

  onExtensionEvent(listener: (event: PiExtensionEvent) => void): () => void {
    this.extensionListeners.add(listener);
    return () => this.extensionListeners.delete(listener);
  }

  async sendCommand(command: RpcCommand): Promise<RpcResponse> {
    const isUserMessage =
      command.type === "prompt" ||
      command.type === "steer" ||
      command.type === "follow_up";
    if (isUserMessage && command.id) {
      this.pendingUserMessages.push({
        id: command.id,
        message: command.message,
        type: command.type,
      });
    }
    if (command.type !== "bash") {
      try {
        const response = await sendPiRpcCommand(this.client, command);
        if (!response.success && isUserMessage && command.id) {
          this.removePendingUserMessageId(command.id);
        }
        return response;
      } catch (error) {
        if (isUserMessage && command.id) {
          this.removePendingUserMessageId(command.id);
        }
        throw error;
      }
    }

    if (this.directBashActive) {
      throw new Error("A Pi bash command is already running");
    }
    this.directBashActive = true;
    this.emitConversationEvents(
      this.translator.beginDirectBash(command.command),
    );
    try {
      const response = await sendPiRpcCommand(this.client, command);
      if (response.success) {
        const result = (response as { data: PiDirectBashResult }).data;
        this.emitConversationEvents(this.translator.completeDirectBash(result));
      } else {
        this.emitConversationEvents(
          this.translator.failDirectBash(response.error),
        );
      }
      return response;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.emitConversationEvents(this.translator.failDirectBash(message));
      throw error;
    } finally {
      this.directBashActive = false;
    }
  }

  clearPendingQueuedUserMessages(): void {
    for (let index = this.pendingUserMessages.length - 1; index >= 0; index--) {
      if (this.pendingUserMessages[index]?.type !== "prompt") {
        this.pendingUserMessages.splice(index, 1);
      }
    }
  }

  private handleEvent(event: JsonAgentSessionEvent | PiExtensionEvent): void {
    if (
      event.type === "extension_ui_request" ||
      event.type === "extension_error"
    ) {
      for (const listener of this.extensionListeners) {
        listener(event);
      }
      return;
    }

    for (const listener of this.runtimeListeners) {
      listener(event);
    }

    const conversationEvents = this.translator.translateEvent(event);
    for (const conversationEvent of conversationEvents) {
      if (conversationEvent.type === "user_message") {
        const text = conversationEvent.content
          .filter((content) => content.type === "text")
          .map((content) => content.text)
          .join("");
        const pendingIndex = this.pendingUserMessages.findIndex(
          (pending) => pending.message === text,
        );
        if (pendingIndex >= 0) {
          const [pending] = this.pendingUserMessages.splice(pendingIndex, 1);
          conversationEvent.id = pending.id;
        }
      }
    }
    this.emitConversationEvents(conversationEvents);
  }

  private removePendingUserMessageId(messageId: string): void {
    const index = this.pendingUserMessages.findIndex(
      (pending) => pending.id === messageId,
    );
    if (index >= 0) {
      this.pendingUserMessages.splice(index, 1);
    }
  }

  private emitConversationEvents(events: AgentConversationEvent[]): void {
    for (const event of events) {
      for (const listener of this.conversationListeners) {
        listener(event);
      }
    }
  }
}
