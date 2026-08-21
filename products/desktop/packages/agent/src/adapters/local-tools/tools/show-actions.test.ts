import { describe, expect, it } from "vitest";
import { enabledLocalTools } from "../index";
import { SHOW_ACTIONS_TOOL_NAME, showActionsSchema } from "./show-actions";

describe("show_actions tool", () => {
  // The tool exists because a gated tool the agent never sees cannot be offered.
  // Every gate meta a session can carry must still expose it.
  it.each([
    { name: "a local session", meta: { environment: "local" as const } },
    {
      name: "a headless cloud run",
      meta: { environment: "cloud" as const, background: true },
    },
    { name: "a channel session", meta: { channelMode: true } },
    { name: "no gate meta at all", meta: undefined },
  ])("is exposed in $name", ({ meta }) => {
    const tools = enabledLocalTools({ cwd: "/repo" }, meta);
    expect(tools.some((t) => t.name === SHOW_ACTIONS_TOOL_NAME)).toBe(true);
  });

  it.each([
    {
      name: "an empty list",
      actions: [],
    },
    {
      name: "more than four actions",
      actions: Array.from({ length: 5 }, () => ({
        kind: "compose",
        label: "Do it",
        prompt: "Do it",
      })),
    },
    {
      name: "a label over 60 characters",
      actions: [{ kind: "compose", label: "x".repeat(61), prompt: "Do it" }],
    },
    {
      name: "a url instead of a verb",
      actions: [{ kind: "open_url", label: "Open", url: "https://evil.test" }],
    },
  ])("rejects $name", ({ actions }) => {
    expect(showActionsSchema.actions.safeParse(actions).success).toBe(false);
  });

  it("accepts one of each verb", () => {
    expect(
      showActionsSchema.actions.safeParse([
        {
          kind: "compose",
          label: "Fix it",
          prompt: "Fix the bug",
          repo: "a/b",
        },
        { kind: "open_space", label: "Open space", channel_id: "chan" },
        {
          kind: "open_canvas",
          label: "Open canvas",
          channel_id: "chan",
          canvas_id: "dash",
        },
      ]).success,
    ).toBe(true);
  });
});
