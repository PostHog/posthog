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

  it("adds hidden context before model dispatch without mutating the input", async () => {
    const { selector, send } = fixture();
    await selector.dispatch("r", "m", prompt, send);
    expect(send.mock.calls[0][0]).toEqual([
      ...prompt,
      {
        type: "text",
        text: "retrieved definition",
        _meta: { ui: { hidden: true } },
      },
    ]);
    expect(prompt).toHaveLength(1);
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

  it("leaves shadow turns unchanged", async () => {
    const { api, selector, send } = fixture();
    api.prepareContextSelection.mockResolvedValue({
      selection_id: "s",
      context: "",
      mode: "shadow",
    });
    await selector.dispatch("r", "m", prompt, send);
    expect(send).toHaveBeenCalledWith(prompt);
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

  it("preserves adapter failures", async () => {
    const { selector, send } = fixture();
    const error = new Error("adapter failed");
    send.mockRejectedValue(error);
    await expect(selector.dispatch("r", "m", prompt, send)).rejects.toBe(error);
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
    await selector.dispatch("r", "next", [{ type: "text", text: "Yes" }], send);
    expect(api.prepareContextSelection.mock.calls[1][0].history).toContain(
      "Earlier conversation summary",
    );
    selector.resetHistory("r");
    await selector.dispatch("r", "cleared", prompt, send);
    expect(api.prepareContextSelection.mock.calls[2][0].history).toBe("");
  });

  it("uses native resume history on subsequent turns", async () => {
    const { api, selector, send } = fixture();
    selector.resetHistory("r", "Earlier native conversation");
    await selector.dispatch("r", "m", prompt, send);
    await selector.dispatch("r", "m2", prompt, send);
    expect(api.prepareContextSelection.mock.calls[0][0].history).toBe(
      "Earlier native conversation",
    );
    expect(api.prepareContextSelection.mock.calls[1][0].history).toContain(
      "Earlier native conversation",
    );
  });

  it("does not select or retain slash commands", async () => {
    const { api, selector, send } = fixture();
    await selector.dispatch(
      "r",
      "clear",
      [{ type: "text", text: "/clear" }],
      send,
    );
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
    await selector.dispatch("r", "m", prompt, send);
    expect(api.prepareContextSelection.mock.calls[0][0].history).toBe("");
  });

  it.each([true, false])(
    "validates Unicode code points at the context boundary: %s",
    (withinBudget) => {
      const context = "😀".repeat(withinBudget ? 8_000 : 8_001);
      expect(
        contextSelectionResponseSchema.safeParse({
          selection_id: "s",
          context,
          mode: "treatment",
          reason: "selected",
        }).success,
      ).toBe(withinBudget);
    },
  );

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
