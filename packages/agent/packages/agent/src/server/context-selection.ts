import type { PostHogAPIClient } from "../posthog-api";

export interface HumanMessage {
  messageId: string;
  text: string;
}

function tail(value: string, limit: number): string {
  return Array.from(value).slice(-limit).join("");
}

export class ContextSelection {
  private history = "";

  constructor(
    private readonly api: Pick<PostHogAPIClient, "prepareContextSelection">,
    private readonly runId: string,
    private readonly report: (
      event: Record<string, unknown>,
    ) => void = () => {},
    private readonly runtimeVersion = "unknown",
    history = "",
  ) {
    this.resetHistory(history);
  }

  resetHistory(history = ""): void {
    this.history = tail(history, 12_000);
  }

  async prepare(message: HumanMessage): Promise<string> {
    if (message.text.trimStart().startsWith("/")) return "";
    try {
      const prepared = await this.api.prepareContextSelection({
        run_id: this.runId,
        message_id: message.messageId,
        prompt: tail(message.text, 20_000),
        history: this.history,
        runtime_version: this.runtimeVersion,
      });
      return prepared.context;
    } catch {
      this.report({
        event: "prepare_failed",
        run_id: this.runId,
        message_id: message.messageId,
      });
      return "";
    }
  }

  recordTurn(message: HumanMessage | undefined, assistantText: string): void {
    if (message?.text.trimStart().startsWith("/")) return;
    if (message)
      this.history = tail(`${this.history}\nUser: ${message.text}`, 12_000);
    if (assistantText)
      this.history = tail(
        `${this.history}\nAssistant: ${assistantText}`,
        12_000,
      );
  }
}
