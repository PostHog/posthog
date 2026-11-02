import { describe, expect, it, vi } from "vitest";
import { contextSelectionResponseSchema } from "../context-selection/schemas";
import { PostHogAPIError } from "../posthog-api";
import { ContextSelection } from "./context-selection";

const message = { messageId: "m", text: "How is activation defined?" };

function fixture(runId = "r", history = "") {
  const api = {
    prepareContextSelection: vi.fn().mockResolvedValue({
      selection_id: "s",
      context: "retrieved definition",
      mode: "treatment",
      reason: "selected",
    }),
  };
  const report = vi.fn();
  const selector = new ContextSelection(api, runId, report, "test", history);
  return { api, selector, report };
}

describe("cloud context selection", () => {
  it.each([
    ["disabled", "disabled", true],
    ["disabled", "error", false],
    ["control", "control", false],
    ["shadow", "selected", false],
    ["treatment", "gate_skipped", false],
  ])(
    "only stops preparation for an explicit disabled result: %s/%s",
    async (mode, reason, disabled) => {
      const { api, selector } = fixture();
      api.prepareContextSelection.mockResolvedValueOnce({
        selection_id: "",
        context: "",
        mode,
        reason,
      });
      expect(await selector.prepare(message)).toBe("");
      selector.resetHistory();
      expect(await selector.prepare(message)).toBe(
        disabled ? "" : "retrieved definition",
      );
      expect(api.prepareContextSelection).toHaveBeenCalledTimes(
        disabled ? 1 : 2,
      );
      const nextSession = new ContextSelection(api, "next");
      expect(await nextSession.prepare(message)).toBe("retrieved definition");
    },
  );

  it("keeps the human request separate from restored history", async () => {
    const { api, selector } = fixture("r", "Earlier conversation summary");
    expect(await selector.prepare(message)).toBe("retrieved definition");
    expect(api.prepareContextSelection).toHaveBeenCalledWith({
      run_id: "r",
      message_id: "m",
      prompt: message.text,
      history: "Earlier conversation summary",
      runtime_version: "test",
    });
    selector.recordTurn(message, "Activation means the first useful action.");
    await selector.prepare({ messageId: "next", text: "What changed?" });
    expect(api.prepareContextSelection.mock.lastCall?.[0].history).toContain(
      "first useful action",
    );
    selector.resetHistory();
    await selector.prepare(message);
    expect(api.prepareContextSelection.mock.lastCall?.[0].history).toBe("");
  });

  it.each([
    [new PostHogAPIError("sensitive response body", 403), "http", 403],
    [
      new DOMException("sensitive timeout details", "TimeoutError"),
      "timeout",
      undefined,
    ],
    [
      contextSelectionResponseSchema.safeParse({}).error,
      "response_validation",
      undefined,
    ],
    [new Error("sensitive transport details"), "transport", undefined],
  ])(
    "returns no enrichment and safe diagnostics on %s",
    async (error, category, status) => {
      const { api, selector, report } = fixture();
      api.prepareContextSelection.mockRejectedValue(error);
      expect(await selector.prepare(message)).toBe("");
      expect(report).toHaveBeenCalledWith({
        event: "prepare_failed",
        run_id: "r",
        message_id: "m",
        error_type: category,
        ...(status ? { http_status: status } : {}),
      });
      api.prepareContextSelection.mockResolvedValueOnce({
        selection_id: "s",
        context: "retrieved definition",
        mode: "treatment",
        reason: "selected",
      });
      expect(await selector.prepare(message)).toBe("retrieved definition");
    },
  );

  it.each(["x", "😀"])(
    "bounds Unicode history and requests: %s",
    async (character) => {
      const { api, selector } = fixture();
      selector.recordTurn(undefined, character.repeat(12_001));
      await selector.prepare({
        messageId: "long",
        text: character.repeat(20_001),
      });
      const input = api.prepareContextSelection.mock.lastCall?.[0];
      expect(Array.from(input.history).length).toBe(12_000);
      expect(input.prompt).toBe(character.repeat(20_000));
    },
  );

  it("does not select or retain slash commands", async () => {
    const { api, selector } = fixture();
    const command = { messageId: "clear", text: "/clear" };
    expect(await selector.prepare(command)).toBe("");
    selector.recordTurn(command, "Cleared");
    expect(api.prepareContextSelection).not.toHaveBeenCalled();
    await selector.prepare(message);
    expect(api.prepareContextSelection.mock.lastCall?.[0].history).toBe("");
  });

  it("keeps late results in their originating session", async () => {
    const oldSession = fixture("old");
    const newSession = fixture("new");
    oldSession.selector.recordTurn(message, "late previous answer");
    await newSession.selector.prepare(message);
    expect(
      newSession.api.prepareContextSelection.mock.lastCall?.[0],
    ).toMatchObject({ run_id: "new", history: "" });
  });

  it.each([true, false])(
    "validates Unicode context bounds: %s",
    (withinBudget) => {
      expect(
        contextSelectionResponseSchema.safeParse({
          selection_id: "s",
          context: "😀".repeat(withinBudget ? 8_000 : 8_001),
          mode: "treatment",
          reason: "selected",
        }).success,
      ).toBe(withinBudget);
    },
  );

  it("rejects context on a control response", () => {
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
