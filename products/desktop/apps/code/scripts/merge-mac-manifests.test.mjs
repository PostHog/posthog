import { describe, expect, it } from "vitest";
import { mergeManifests } from "./merge-mac-manifests.mjs";

const arm64Manifest = () => ({
  version: "1.2.3",
  releaseDate: "2026-06-20T00:00:00.000Z",
  path: "PostHog-Code-1.2.3-arm64-mac.zip",
  sha512: "arm64-sha",
  files: [
    { url: "PostHog-Code-1.2.3-arm64-mac.zip", sha512: "arm64-sha", size: 1 },
  ],
});

const x64Manifest = () => ({
  version: "1.2.3",
  releaseDate: "2026-06-20T00:00:01.000Z",
  path: "PostHog-Code-1.2.3-x64-mac.zip",
  sha512: "x64-sha",
  files: [
    { url: "PostHog-Code-1.2.3-x64-mac.zip", sha512: "x64-sha", size: 2 },
  ],
});

describe("mergeManifests", () => {
  it("combines distinct files from both manifests, arm64 first", () => {
    const merged = mergeManifests(arm64Manifest(), x64Manifest());

    expect(merged.files.map((f) => f.url)).toEqual([
      "PostHog-Code-1.2.3-arm64-mac.zip",
      "PostHog-Code-1.2.3-x64-mac.zip",
    ]);
  });

  it("dedupes files that share a url, keeping the arm64 entry", () => {
    const shared = { url: "shared.zip", sha512: "from-arm64", size: 1 };
    const arm64 = { ...arm64Manifest(), files: [shared] };
    const x64 = {
      ...x64Manifest(),
      files: [{ url: "shared.zip", sha512: "from-x64", size: 2 }],
    };

    const merged = mergeManifests(arm64, x64);

    expect(merged.files).toHaveLength(1);
    expect(merged.files[0].sha512).toBe("from-arm64");
  });

  it("keeps arch-independent metadata but drops single-arch top-level fields", () => {
    const merged = mergeManifests(arm64Manifest(), x64Manifest());

    expect(merged.version).toBe("1.2.3");
    expect(merged.releaseDate).toBe("2026-06-20T00:00:00.000Z");
    // path/sha512/size describe one file and are meaningless for a merged
    // multi-arch manifest; electron-updater reads files[] instead.
    expect(merged.path).toBeUndefined();
    expect(merged.sha512).toBeUndefined();
    expect(merged.size).toBeUndefined();
  });

  it("throws when the two manifests report different versions", () => {
    const x64 = { ...x64Manifest(), version: "1.2.4" };

    expect(() => mergeManifests(arm64Manifest(), x64)).toThrow(
      "version mismatch",
    );
  });

  it("keeps the entries from the non-empty side when one has no files", () => {
    const arm64 = { ...arm64Manifest(), files: [] };

    const merged = mergeManifests(arm64, x64Manifest());

    expect(merged.files.map((f) => f.url)).toEqual([
      "PostHog-Code-1.2.3-x64-mac.zip",
    ]);
  });

  it("returns an empty file list when both sides are empty", () => {
    const arm64 = { ...arm64Manifest(), files: [] };
    const x64 = { ...x64Manifest(), files: [] };

    expect(mergeManifests(arm64, x64).files).toEqual([]);
  });
});
