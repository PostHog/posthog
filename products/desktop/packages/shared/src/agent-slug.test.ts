import { describe, expect, it } from "vitest";
import { isValidAgentSlug } from "./agent-slug";

describe("isValidAgentSlug", () => {
  it.each(["a", "my-agent", "agent123", "A1-b2", "x".repeat(63)])(
    "accepts the DNS label %s",
    (slug) => {
      expect(isValidAgentSlug(slug)).toBe(true);
    },
  );

  it.each([
    "evil.com",
    "evil.com/",
    "evil.com#x",
    "evil.com?x",
    "evil.com:9999/",
    "evil.com\\x",
    "user@evil.com",
    "foo/../bar",
    "foo bar",
    "-lead",
    "trail-",
    "under_score",
    "x".repeat(64),
    "",
    null,
    undefined,
  ])("rejects %s", (slug) => {
    expect(isValidAgentSlug(slug)).toBe(false);
  });
});
