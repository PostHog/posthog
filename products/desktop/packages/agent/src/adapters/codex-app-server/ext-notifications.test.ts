import { describe, expect, it } from "vitest";
import { emptyBaseline } from "../claude/context-breakdown";
import {
  buildSdkSessionParams,
  buildTurnCompleteParams,
  buildUsageBreakdownParams,
} from "./ext-notifications";

describe("ext-notifications builders", () => {
  it("buildSdkSessionParams tags the codex adapter so resume keys on the family", () => {
    expect(buildSdkSessionParams("sess-1", "run-42")).toEqual({
      taskRunId: "run-42",
      sessionId: "sess-1",
      adapter: "codex",
    });
  });

  it("buildTurnCompleteParams derives totalTokens from all four counts", () => {
    const params = buildTurnCompleteParams("sess-1", "end_turn", {
      inputTokens: 100,
      outputTokens: 20,
      cachedReadTokens: 5,
      cachedWriteTokens: 3,
    });

    expect(params).toEqual({
      sessionId: "sess-1",
      stopReason: "end_turn",
      usage: {
        inputTokens: 100,
        outputTokens: 20,
        cachedReadTokens: 5,
        cachedWriteTokens: 3,
        totalTokens: 128,
      },
    });
  });

  it("buildTurnCompleteParams forwards non-default stop reasons", () => {
    expect(
      buildTurnCompleteParams("sess-1", "refusal", {
        inputTokens: 0,
        outputTokens: 0,
        cachedReadTokens: 0,
        cachedWriteTokens: 0,
      }).stopReason,
    ).toBe("refusal");
  });

  it("buildUsageBreakdownParams attributes overflow above the baseline to conversation", () => {
    const baseline = { ...emptyBaseline(), systemPrompt: 1000, tools: 500 };

    expect(buildUsageBreakdownParams("sess-1", baseline, 2000)).toEqual({
      sessionId: "sess-1",
      breakdown: {
        systemPrompt: 1000,
        tools: 500,
        rules: 0,
        skills: 0,
        mcp: 0,
        subagents: 0,
        conversation: 500,
      },
    });
  });

  it("buildUsageBreakdownParams floors conversation at 0 when usage is below baseline", () => {
    const baseline = { ...emptyBaseline(), systemPrompt: 1000 };

    expect(
      buildUsageBreakdownParams("sess-1", baseline, 200).breakdown.conversation,
    ).toBe(0);
  });
});
