import { createHash, randomUUID } from "node:crypto";
import type { ContentBlock, PromptResponse } from "@agentclientprotocol/sdk";
import type { PostHogAPIClient } from "../posthog-api";
import { hiddenTextBlock } from "./cloud-prompt";

function hash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function isHidden(block: ContentBlock): boolean {
  const ui = block._meta?.ui;
  return (
    typeof ui === "object" &&
    ui !== null &&
    "hidden" in ui &&
    ui.hidden === true
  );
}

function text(prompt: ContentBlock[]): string {
  return prompt
    .flatMap((block) => (block.type === "text" ? [block.text] : []))
    .join("\n");
}

/** One instance per cloud process. Only actual human turns call dispatch. */
export class ContextSelection {
  enabled = false;
  private history = "";

  constructor(
    private readonly api: PostHogAPIClient,
    private readonly report: (
      event: Record<string, unknown>,
    ) => void = () => {},
    private readonly runtimeVersion = "unknown",
  ) {}

  async dispatch(
    runId: string,
    messageId: string | undefined,
    prompt: ContentBlock[],
    send: (blocks: ContentBlock[]) => Promise<PromptResponse>,
  ): Promise<PromptResponse> {
    if (!this.enabled || !messageId) return send(prompt);
    let prepared:
      | Awaited<ReturnType<PostHogAPIClient["prepareContextSelection"]>>
      | undefined;
    const userText = text(prompt.filter((block) => !isHidden(block)));
    const history =
      this.history || text(prompt.filter(isHidden)).slice(-12_000);
    try {
      prepared = await this.api.prepareContextSelection({
        run_id: runId,
        message_id: messageId,
        prompt: userText.slice(-20_000),
        prompt_char_count: userText.length,
        history,
        history_source: this.history ? "runtime" : "resume_prompt",
        baseline: hash(prompt),
        runtime_version: this.runtimeVersion,
      });
    } catch {
      this.report({
        event: "prepare_failed",
        run_id: runId,
        message_id: messageId,
      });
      // Selection is optional. An unavailable evidence store must never produce an injection.
    }
    let submitted = prepared?.context
      ? [...prompt, hiddenTextBlock(prepared.context)]
      : prompt;
    const deliveryId = randomUUID();
    let sentAt: number | undefined;
    const receipt = async (
      status: "dispatching" | "completed" | "failed",
      result?: PromptResponse,
    ): Promise<boolean> => {
      if (!prepared?.selection_id) return true;
      try {
        await this.api.recordContextSelectionReceipt({
          run_id: runId,
          selection_id: prepared.selection_id,
          delivery_id: deliveryId,
          status,
          context_included: submitted !== prompt,
          prompt_hash: hash(submitted),
          prompt: submitted,
          stop_reason: result?.stopReason ?? "",
          adapter_elapsed_ms:
            sentAt === undefined ? undefined : performance.now() - sentAt,
          usage: result && "usage" in result ? result.usage : null,
          trace_id:
            typeof result?._meta?.traceId === "string"
              ? result._meta.traceId
              : "",
        });
        return true;
      } catch {
        this.report({
          event: "receipt_failed",
          status,
          run_id: runId,
          message_id: messageId,
          selection_id: prepared.selection_id,
          context_included: submitted !== prompt,
        });
        return false;
      }
    };
    if (!(await receipt("dispatching"))) {
      submitted = prompt;
      await receipt("dispatching");
    }
    try {
      sentAt = performance.now();
      const result = await send(submitted);
      await receipt("completed", result);
      this.history = `${this.history}\nUser: ${userText}`.slice(-12_000);
      return result;
    } catch (error) {
      await receipt("failed");
      throw error;
    }
  }

  recordAssistant(text: string): void {
    if (!this.enabled) return;
    this.history = `${this.history}\nAssistant: ${text}`.slice(-12_000);
  }
}
