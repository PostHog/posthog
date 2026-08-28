import { describe, expect, it } from "vitest";
import {
  fromCachedImageUrl,
  isCacheableImageUrl,
  toCachedImageUrl,
} from "./disk-cache-protocol";

describe("disk-cache-protocol", () => {
  it.each([
    "https://www.gravatar.com/avatar/abc?s=96&d=404",
    "https://avatars.githubusercontent.com/u/1?v=4",
    "https://example.com/a b/%C3%A4.png?x=1&y=%2F#frag",
  ])("round-trips %s through the cache URL", (remoteUrl) => {
    expect(fromCachedImageUrl(toCachedImageUrl(remoteUrl))).toBe(remoteUrl);
  });

  it.each([
    ["http://example.com/a.png", "plain http"],
    ["file:///etc/passwd", "file scheme"],
    ["not a url", "malformed"],
  ])("refuses to cache %s (%s)", (remoteUrl) => {
    expect(isCacheableImageUrl(remoteUrl)).toBe(false);
  });

  it.each([
    [
      "posthog-cache://images/?src=http%3A%2F%2Fexample.com%2Fa.png",
      "http source",
    ],
    [
      "posthog-cache://other/?src=https%3A%2F%2Fexample.com%2Fa.png",
      "unknown namespace",
    ],
    [
      "https://example.com/?src=https%3A%2F%2Fexample.com%2Fa.png",
      "wrong scheme",
    ],
    ["posthog-cache://images/", "missing src"],
  ])("rejects %s (%s)", (protocolUrl) => {
    expect(fromCachedImageUrl(protocolUrl)).toBeNull();
  });
});
