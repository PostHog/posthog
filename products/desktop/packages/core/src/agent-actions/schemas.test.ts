import { describe, expect, it } from "vitest";
import { agentActionSchema } from "./schemas";

describe("agentActionSchema", () => {
  // The agent picks these fields from context it does not control, so a blank required field
  // has to be rejected here. Letting it through leaves a button that silently does nothing.
  it.each([
    ["a blank compose prompt", { kind: "compose", prompt: "   " }],
    ["a missing space id", { kind: "open_space", channel_id: "" }],
    [
      "a missing canvas id",
      { kind: "open_canvas", channel_id: "chan", canvas_id: "" },
    ],
    [
      "a blank canvas channel id",
      { kind: "open_canvas", channel_id: "  ", canvas_id: "dash" },
    ],
    ["an unknown verb", { kind: "open_website", url: "https://evil.example" }],
  ])("rejects %s", (_name, action) => {
    expect(agentActionSchema.safeParse(action).success).toBe(false);
  });

  it("drops a label rather than carrying it into a link", () => {
    const parsed = agentActionSchema.parse({
      kind: "open_space",
      channel_id: "chan",
      label: "Open the space",
    });

    expect(parsed).toEqual({ kind: "open_space", channel_id: "chan" });
  });

  it("keeps an optional repo but drops a blank one", () => {
    expect(
      agentActionSchema.parse({
        kind: "compose",
        prompt: "Do it",
        repo: "posthog/posthog",
      }),
    ).toEqual({ kind: "compose", prompt: "Do it", repo: "posthog/posthog" });
    expect(
      agentActionSchema.safeParse({
        kind: "compose",
        prompt: "Do it",
        repo: "  ",
      }).success,
    ).toBe(false);
  });
});
