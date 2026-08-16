import { LLM_GATEWAY_SERVICE } from "@posthog/core/llm-gateway/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import { inject, injectable } from "inversify";
import { createStore, type StoreApi } from "zustand/vanilla";

const MAX_MAIN_CONVERSATION_CHARS = 40_000;
const SIDE_CHAT_SYSTEM_PROMPT = `You answer questions in a side chat attached to a coding task.

Use the main conversation only as background. Answer the side-chat question directly and concisely. Do not claim to have edited files, run tools, or changed the main task. If the available context is insufficient, say what is unknown and suggest the next question to ask the main agent.`;

export const SIDE_CHAT_SERVICE = Symbol.for(
  "posthog.core.sessions.sideChatService",
);

export interface SideChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export interface SideChatThread {
  messages: SideChatMessage[];
  isLoading: boolean;
  hasError: boolean;
}

export interface SideChatState {
  threads: Record<string, SideChatThread>;
}

const emptyThread = (): SideChatThread => ({
  messages: [],
  isLoading: false,
  hasError: false,
});

@injectable()
export class SideChatService {
  readonly store: StoreApi<SideChatState> = createStore<SideChatState>(() => ({
    threads: {},
  }));

  private nextMessageId = 1;

  constructor(
    @inject(LLM_GATEWAY_SERVICE)
    private readonly llmGateway: LlmGatewayService,
  ) {}

  async ask(
    taskId: string,
    question: string,
    mainConversation: string,
  ): Promise<void> {
    const normalizedQuestion = question.trim();
    const currentThread =
      this.store.getState().threads[taskId] ?? emptyThread();
    if (!normalizedQuestion || currentThread.isLoading) {
      return;
    }

    const userMessage = this.createMessage("user", normalizedQuestion);
    const messages = [...currentThread.messages, userMessage];
    this.setThread(taskId, {
      messages,
      isLoading: true,
      hasError: false,
    });

    try {
      const context = mainConversation.slice(-MAX_MAIN_CONVERSATION_CHARS);
      const result = await this.llmGateway.prompt(
        messages.map(({ role, content }) => ({ role, content })),
        {
          system: `${SIDE_CHAT_SYSTEM_PROMPT}\n\n<main_conversation>\n${context || "No main conversation is available."}\n</main_conversation>`,
          maxTokens: 2_000,
        },
      );
      const answer = result.content.trim();
      if (!answer) {
        throw new Error("The side chat returned an empty answer");
      }
      this.setThread(taskId, {
        messages: [...messages, this.createMessage("assistant", answer)],
        isLoading: false,
        hasError: false,
      });
    } catch {
      this.setThread(taskId, {
        messages,
        isLoading: false,
        hasError: true,
      });
    }
  }

  private createMessage(
    role: SideChatMessage["role"],
    content: string,
  ): SideChatMessage {
    const id = `side-chat-${this.nextMessageId}`;
    this.nextMessageId += 1;
    return { id, role, content };
  }

  private setThread(taskId: string, thread: SideChatThread): void {
    this.store.setState((state) => ({
      threads: { ...state.threads, [taskId]: thread },
    }));
  }
}
