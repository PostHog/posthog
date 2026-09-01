import { describe, expect, it } from "vitest";
import { isSafeExternalUrl, isSafePostHogUrl } from "./url";

describe("isSafeExternalUrl", () => {
  it.each([
    "https://github.com/PostHog/code/pull/42",
    "http://example.com",
    "https://example.com/path?q=1#frag",
    "HTTPS://EXAMPLE.COM",
    "mailto:hi@posthog.com",
  ])("allows %s", (url) => {
    expect(isSafeExternalUrl(url)).toBe(true);
  });

  it.each([
    "javascript:alert(1)",
    "file:///etc/passwd",
    "data:text/html,<script>alert(1)</script>",
    "smb://server/share",
    "ms-msdt:/id",
    "vscode://extension",
    "//evil.com",
    "/relative/path",
    "not a url",
    "",
    "   ",
  ])("blocks %s", (url) => {
    expect(isSafeExternalUrl(url)).toBe(false);
  });
});

describe("isSafePostHogUrl", () => {
  it.each([
    "https://posthog.com",
    "https://posthog.com/docs?q=1#frag",
    "https://us.posthog.com/project/2",
    "https://app.posthog.com",
    "HTTPS://POSTHOG.COM/pricing",
  ])("allows %s", (url) => {
    expect(isSafePostHogUrl(url)).toBe(true);
  });

  it.each([
    "http://posthog.com",
    "https://example.com",
    "https://myposthog.com",
    "https://evilposthog.com",
    "https://posthog.com.evil.com",
    "mailto:hi@posthog.com",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "posthog.com/docs",
    "/relative/path",
    "",
  ])("blocks %s", (url) => {
    expect(isSafePostHogUrl(url)).toBe(false);
  });
});
