import { describe, expect, it } from "vitest";
import { buildGithubFileUrl, computeSkipExpansion } from "./reviewItemKeys";

describe("computeSkipExpansion", () => {
  it("skips when staged", () => {
    expect(computeSkipExpansion(true, "a.ts", undefined)).toBe(true);
  });

  it("skips when the path is also staged elsewhere", () => {
    expect(computeSkipExpansion(false, "a.ts", new Set(["a.ts"]))).toBe(true);
  });

  it("does not skip an unstaged path with no overlap", () => {
    expect(computeSkipExpansion(false, "a.ts", new Set(["b.ts"]))).toBe(false);
  });

  it("does not skip when alsoStagedPaths is undefined", () => {
    expect(computeSkipExpansion(false, "a.ts", undefined)).toBe(false);
  });
});

describe("buildGithubFileUrl", () => {
  it("returns undefined without a prUrl", () => {
    expect(buildGithubFileUrl(null, "src/a.ts")).toBeUndefined();
  });

  it("builds an anchored files URL with slashes replaced by dashes", () => {
    expect(buildGithubFileUrl("https://gh/pr/1", "src/a/b.ts")).toBe(
      "https://gh/pr/1/files#diff-src-a-b.ts",
    );
  });
});
