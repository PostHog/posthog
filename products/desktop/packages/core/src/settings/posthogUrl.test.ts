import { describe, expect, it } from "vitest";
import { buildPostHogUrl } from "./posthogUrl";

describe("buildPostHogUrl", () => {
  it("passes through absolute URLs", () => {
    expect(buildPostHogUrl("https://x.com/y", "us")).toBe("https://x.com/y");
  });

  it("returns null without a region", () => {
    expect(buildPostHogUrl("/settings", null)).toBeNull();
  });

  it("prefixes the region base and normalizes the leading slash", () => {
    expect(buildPostHogUrl("settings/user", "us")).toBe(
      buildPostHogUrl("/settings/user", "us"),
    );
  });
});
