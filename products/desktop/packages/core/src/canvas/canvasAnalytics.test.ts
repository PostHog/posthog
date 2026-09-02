import { describe, expect, it } from "vitest";
import {
  buildCanvasPromptProps,
  buildContextSaveProps,
  dashboardIdFromThread,
} from "./canvasAnalytics";

describe("dashboardIdFromThread", () => {
  it("strips the dashboard: prefix", () => {
    expect(dashboardIdFromThread("dashboard:abc-123")).toBe("abc-123");
  });

  it("leaves an unprefixed id untouched", () => {
    expect(dashboardIdFromThread("abc-123")).toBe("abc-123");
  });
});

describe("buildCanvasPromptProps", () => {
  it("resolves dashboard id and prompt length for a free-typed prompt", () => {
    expect(
      buildCanvasPromptProps({
        surface: "json",
        threadId: "dashboard:d1",
        text: "hello",
        fromSuggestion: false,
      }),
    ).toEqual({
      surface: "json",
      dashboard_id: "d1",
      from_suggestion: false,
      prompt_length_chars: 5,
    });
  });

  it("flags suggestion-driven prompts", () => {
    const props = buildCanvasPromptProps({
      surface: "freeform",
      threadId: "dashboard:d2",
      text: "build a chart",
      fromSuggestion: true,
    });
    expect(props.from_suggestion).toBe(true);
    expect(props.surface).toBe("freeform");
  });

  it("passes through the ask_agent_to_fix intent and omits it otherwise", () => {
    const withIntent = buildCanvasPromptProps({
      surface: "freeform",
      threadId: "dashboard:d3",
      text: "fix it",
      fromSuggestion: false,
      intent: "ask_agent_to_fix",
    });
    expect(withIntent.intent).toBe("ask_agent_to_fix");

    const withoutIntent = buildCanvasPromptProps({
      surface: "freeform",
      threadId: "dashboard:d3",
      text: "fix it",
      fromSuggestion: false,
    });
    expect(withoutIntent).not.toHaveProperty("intent");
  });
});

describe("buildContextSaveProps", () => {
  // is_first_version is the negation of hasInstructions; success passes through
  // independently. The table covers both inputs against both outcomes.
  it.each([
    { hasInstructions: false, success: true, is_first_version: true },
    { hasInstructions: true, success: true, is_first_version: false },
    { hasInstructions: false, success: false, is_first_version: true },
    { hasInstructions: true, success: false, is_first_version: false },
  ])(
    "hasInstructions=$hasInstructions success=$success → is_first_version=$is_first_version",
    ({ hasInstructions, success, is_first_version }) => {
      expect(
        buildContextSaveProps({ channelId: "c1", hasInstructions, success }),
      ).toEqual({
        action_type: "save_version",
        channel_id: "c1",
        is_first_version,
        success,
      });
    },
  );
});
