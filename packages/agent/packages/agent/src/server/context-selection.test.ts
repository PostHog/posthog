import type { ContentBlock, PromptResponse } from "@agentclientprotocol/sdk";
import { describe, expect, it, vi } from "vitest";
import { contextSelectionResponseSchema } from "../context-selection/schemas";
import type { PostHogAPIClient } from "../posthog-api";
import { ContextSelection } from "./context-selection";

const prompt: ContentBlock[] = [
  { type: "text", text: "How is activation defined?" },
];
const response: PromptResponse = {
  stopReason: "end_turn",
  _meta: { traceId: "actual-turn" },
};

function fixture() {
  const api = {
    prepareContextSelection: vi.fn().mockResolvedValue({
      selection_id: "s",
      context: "retrieved definition",
      mode: "treatment",
      reason: "selected",
    }),
    recordContextSelectionReceipt: vi.fn().mockResolvedValue(undefined),
  };
  const report = vi.fn();
  const selector = new ContextSelection(
    api as unknown as PostHogAPIClient,
    report,
  );
  selector.enabled = true;
  const send = vi.fn().mockResolvedValue(response);
  return { api, selector, send, report };
}

describe("cloud context selection", () => {
  it("does no extra work for ineligible runs or autonomous continuations", async () => {
    const { api, selector, send } = fixture();
    selector.enabled = false;
    await selector.dispatch("r", "m", prompt, send);
    selector.enabled = true;
    await selector.dispatch("r", undefined, prompt, send);
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
    expect(send).toHaveBeenCalledWith(prompt);
  });

  it("archives the actual enriched prompt before sending and records the actual trace", async () => {
    const { api, selector, send } = fixture();
    await selector.dispatch("r", "m", prompt, send);
    const submitted = send.mock.calls[0][0];
    expect(submitted).toHaveLength(2);
    expect(prompt).toHaveLength(1);
    expect(api.recordContextSelectionReceipt.mock.calls[0][0]).toMatchObject({
      status: "dispatching",
      prompt: submitted,
      context_included: true,
    });
    expect(api.recordContextSelectionReceipt.mock.calls[1][0]).toMatchObject({
      status: "completed",
      trace_id: "actual-turn",
      prompt: submitted,
    });
    expect(
      api.recordContextSelectionReceipt.mock.invocationCallOrder[0],
    ).toBeLessThan(send.mock.invocationCallOrder[0]);
  });

  it("records the gateway-stamped trace when the adapter omits a turn trace", async () => {
    const { api, selector, send } = fixture();
    send.mockResolvedValue({ stopReason: "end_turn" });
    await selector.dispatch(
      "r",
      "m",
      prompt,
      send,
      prompt,
      "stamped-run-trace",
    );
    expect(api.recordContextSelectionReceipt.mock.calls[1][0]).toMatchObject({
      status: "completed",
      trace_id: "stamped-run-trace",
    });
  });

  it("prefers the adapter's turn trace over the gateway session trace", async () => {
    const { api, selector, send } = fixture();
    await selector.dispatch(
      "r",
      "m",
      prompt,
      send,
      prompt,
      "stamped-run-trace",
    );
    expect(api.recordContextSelectionReceipt.mock.calls[1][0]).toMatchObject({
      trace_id: "actual-turn",
    });
  });

  it("does not inject when delivery evidence cannot be persisted", async () => {
    const { api, selector, send, report } = fixture();
    api.recordContextSelectionReceipt.mockRejectedValue(
      new Error("unavailable"),
    );
    await selector.dispatch("r", "m", prompt, send);
    expect(send).toHaveBeenCalledWith(prompt);
    expect(report).toHaveBeenCalledWith(
      expect.objectContaining({ event: "receipt_failed" }),
    );
  });

  it("leaves prompts unchanged on selection failure", async () => {
    const { api, selector, send, report } = fixture();
    api.prepareContextSelection.mockRejectedValue(new Error("timeout"));
    await selector.dispatch("r", "m", prompt, send);
    expect(send).toHaveBeenCalledWith(prompt);
    expect(report).toHaveBeenCalledWith(
      expect.objectContaining({ event: "prepare_failed", message_id: "m" }),
    );
  });

  it("captures control and shadow turns without injecting context", async () => {
    const { api, selector, send } = fixture();
    api.prepareContextSelection.mockResolvedValue({
      selection_id: "s",
      context: "",
      mode: "shadow",
    });
    await selector.dispatch("r", "m", prompt, send);
    expect(send).toHaveBeenCalledWith(prompt);
    expect(
      api.recordContextSelectionReceipt.mock.calls[1][0].context_included,
    ).toBe(false);
  });

  it("keeps bounded user and assistant history for follow-ups", async () => {
    const { api, selector, send } = fixture();
    await selector.dispatch("r", "m", prompt, send);
    selector.recordAssistant("r", "Activation means the first useful action.");
    await selector.dispatch(
      "r",
      "m2",
      [{ type: "text", text: "What about last week?" }],
      send,
    );
    expect(api.prepareContextSelection.mock.calls[1][0].history).toContain(
      "first useful action",
    );
    selector.recordAssistant("r", "x".repeat(20_000));
    await selector.dispatch("r", "m3", prompt, send);
    expect(
      api.prepareContextSelection.mock.calls[2][0].history.length,
    ).toBeLessThanOrEqual(12_000);
  });

  it("records adapter errors and preserves the original failure", async () => {
    const { api, selector, send } = fixture();
    const error = new Error("adapter failed");
    send.mockRejectedValue(error);
    await expect(selector.dispatch("r", "m", prompt, send)).rejects.toBe(error);
    expect(
      api.recordContextSelectionReceipt.mock.calls.at(-1)?.[0].status,
    ).toBe("failed");
  });
  it("keeps restored history separate from the current request", async () => {
    const { api, selector, send } = fixture();
    await selector.dispatch(
      "r",
      "m",
      [
        {
          type: "text",
          text: "Earlier conversation summary",
          _meta: { ui: { hidden: true } },
        },
        { type: "text", text: "What changed?" },
      ],
      send,
    );
    expect(api.prepareContextSelection.mock.calls[0][0]).toMatchObject({
      prompt: "What changed?",
      history: "Earlier conversation summary",
      history_source: "resume_prompt",
    });
  });

  it("resets history for another run and ignores late results from the old run", async () => {
    const { api, selector, send } = fixture();
    await selector.dispatch("r", "m", prompt, send);
    selector.recordAssistant("r", "private previous answer");
    await selector.dispatch("new-run", "m2", prompt, send);
    expect(api.prepareContextSelection.mock.calls[1][0].history).toBe("");
    selector.recordAssistant("r", "late previous answer");
    await selector.dispatch("new-run", "m3", prompt, send);
    expect(api.prepareContextSelection.mock.calls[2][0].history).not.toContain(
      "previous answer",
    );
  });

  it("uses a new delivery ID when a context receipt times out before baseline dispatch", async () => {
    const { api, selector, send } = fixture();
    api.recordContextSelectionReceipt.mockRejectedValueOnce(
      new Error("timeout after persistence"),
    );
    await selector.dispatch("r", "m", prompt, send);
    const [enriched, baseline, completed] =
      api.recordContextSelectionReceipt.mock.calls.map(([receipt]) => receipt);
    expect(enriched.delivery_id).not.toBe(baseline.delivery_id);
    expect(completed.delivery_id).toBe(baseline.delivery_id);
    expect(baseline.prompt).toEqual(prompt);
    expect(completed.context_included).toBe(false);
  });

  it("rejects unexpected context on a control response at the API boundary", () => {
    expect(
      contextSelectionResponseSchema.safeParse({
        selection_id: "s",
        context: "unexpected",
        mode: "control",
        reason: "control",
      }).success,
    ).toBe(false);
  });
});
