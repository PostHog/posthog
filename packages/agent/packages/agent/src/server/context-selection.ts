import { ZodError } from "zod/v4";
import { type PostHogAPIClient, PostHogAPIError } from "../posthog-api";

export interface HumanMessage {
  messageId: string;
  text: string;
}

const MAX_EXCLUDED_REFERENCES = 200;

function tail(value: string, limit: number): string {
  return Array.from(value).slice(-limit).join("");
}

export function injectedReferenceKeys(text: string): string[] {
  const keys: string[] = [];
  let inBlock = false;
  for (const line of text.split("\n")) {
    if (line.includes("<posthog_reference_context")) inBlock = true;
    if (line.includes("</posthog_reference_context>")) inBlock = false;
    if (!inBlock || !line.startsWith("{")) continue;
    let record: Record<string, unknown>;
    try {
      record = JSON.parse(line) as Record<string, unknown>;
    } catch {
      continue;
    }
    const id = record.document_id || record.id;
    if (typeof record.kind === "string" && typeof id === "string" && id) {
      keys.push(`${record.kind}:${id}`);
    }
  }
  return keys;
}

export class ContextSelection {
  private history = "";
  private disabled = false;
  private injected = new Set<string>();

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
    this.injected = new Set(injectedReferenceKeys(history));
  }

  forgetInjected(): void {
    this.injected.clear();
  }

  async prepare(message: HumanMessage): Promise<string> {
    if (this.disabled || message.text.trimStart().startsWith("/")) return "";
    try {
      const prepared = await this.api.prepareContextSelection({
        run_id: this.runId,
        message_id: message.messageId,
        prompt: tail(message.text, 20_000),
        history: this.history,
        runtime_version: this.runtimeVersion,
        exclude: [...this.injected].slice(-MAX_EXCLUDED_REFERENCES),
      });
      if (prepared.mode === "disabled" && prepared.reason === "disabled")
        this.disabled = true;
      for (const key of injectedReferenceKeys(prepared.context)) {
        this.injected.add(key);
      }
      return prepared.context;
    } catch (error) {
      const errorType =
        error instanceof PostHogAPIError
          ? "http"
          : error instanceof ZodError
            ? "response_validation"
            : error instanceof Error &&
                (error.name === "TimeoutError" || error.name === "AbortError")
              ? "timeout"
              : "transport";
      this.report({
        event: "prepare_failed",
        run_id: this.runId,
        message_id: message.messageId,
        error_type: errorType,
        ...(error instanceof PostHogAPIError
          ? { http_status: error.status }
          : {}),
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
