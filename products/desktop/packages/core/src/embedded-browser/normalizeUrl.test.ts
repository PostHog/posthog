import { describe, expect, it } from "vitest";
import { normalizeBrowserUrl } from "./normalizeUrl";

describe("normalizeBrowserUrl", () => {
  it.each([
    // already-complete web URLs pass through
    ["https://posthog.com", "https://posthog.com/"],
    ["http://example.com/a?b=1#c", "http://example.com/a?b=1#c"],
    // bare domains get https
    ["posthog.com", "https://posthog.com/"],
    ["app.example.com/login", "https://app.example.com/login"],
    // local dev hosts get http — dev servers rarely terminate TLS
    ["localhost:8000", "http://localhost:8000/"],
    ["localhost:3000/app", "http://localhost:3000/app"],
    ["127.0.0.1:8010", "http://127.0.0.1:8010/"],
    ["localhost", "http://localhost/"],
    // surrounding whitespace is tolerated
    ["  posthog.com  ", "https://posthog.com/"],
  ])("%s → %s", (input, expected) => {
    expect(normalizeBrowserUrl(input)).toBe(expected);
  });

  it.each([
    // non-web schemes are rejected outright, never scheme-prefixed
    "file:///etc/passwd",
    "javascript:alert(1)",
    "mailto:user@example.com",
    "chrome://settings",
    "about:blank",
    "data:text/html,<b>hi</b>",
    // not URLs at all
    "",
    "   ",
    "not a url",
    "https://",
  ])("rejects %s", (input) => {
    expect(normalizeBrowserUrl(input)).toBeNull();
  });
});
