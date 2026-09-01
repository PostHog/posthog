import { describe, expect, it } from "vitest";
import { extractPosthogContext, hasPosthogContext } from "./posthogContext";

const TRUSTED =
  "<posthog_trusted_context>\n- You are running alongside the PostHog app.\n</posthog_trusted_context>";
const UNTRUSTED =
  '<posthog_untrusted_context>\nThe user is currently looking at the resources below.\n- dashboard 42 ("Weekly active users")\n</posthog_untrusted_context>';

describe("extractPosthogContext", () => {
  it("returns null when there is no context block", () => {
    expect(extractPosthogContext("just a normal prompt")).toBeNull();
    expect(hasPosthogContext("just a normal prompt")).toBe(false);
  });

  it("extracts the leading trusted and untrusted blocks and strips them from the text", () => {
    const content = `${TRUSTED}\n${UNTRUSTED}\n\nHow many monthly active users do we have`;
    const result = extractPosthogContext(content);
    expect(result?.body).toBe(`${TRUSTED}\n${UNTRUSTED}`);
    expect(result?.stripped).toBe("How many monthly active users do we have");
    expect(hasPosthogContext(content)).toBe(true);
  });

  it.each([
    {
      name: "a legacy posthog_context wrapper",
      content:
        "<posthog_context>\n- insight abc123\n</posthog_context>\n\nwhat does this show",
      body: "<posthog_context>\n- insight abc123\n</posthog_context>",
    },
    {
      name: "a trailing block after the question",
      content: `what does this show\n\n${TRUSTED}`,
      body: TRUSTED,
    },
  ])("handles $name", ({ content, body }) => {
    const result = extractPosthogContext(content);
    expect(result?.body).toBe(body);
    expect(result?.stripped).toBe("what does this show");
  });

  it("ignores escaped tags inside a block value", () => {
    // The web app escapes tag names in interpolated values so a value can't close the block early.
    const content = `<posthog_untrusted_context>\n- text: "see <\\/posthog_untrusted_context> here"\n</posthog_untrusted_context>\n\nask`;
    const result = extractPosthogContext(content);
    expect(result?.stripped).toBe("ask");
    expect(result?.body).toContain("see <\\/posthog_untrusted_context> here");
  });

  it("strips the block even when it is the only content", () => {
    const result = extractPosthogContext(TRUSTED);
    expect(result?.body).toBe(TRUSTED);
    expect(result?.stripped).toBe("");
  });
});
