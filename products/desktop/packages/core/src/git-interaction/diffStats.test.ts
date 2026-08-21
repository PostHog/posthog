import type { ChangedFile } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";

import { computeDiffStats } from "./diffStats";

describe("computeDiffStats", () => {
  it("sums line counts across text files", () => {
    const files: ChangedFile[] = [
      { path: "src/a.ts", status: "modified", linesAdded: 3, linesRemoved: 1 },
      { path: "src/b.ts", status: "added", linesAdded: 10, linesRemoved: 0 },
    ];
    expect(computeDiffStats(files)).toEqual({
      filesChanged: 2,
      linesAdded: 13,
      linesRemoved: 1,
    });
  });

  it("counts image/video files but excludes their lines from the totals", () => {
    const files: ChangedFile[] = [
      { path: "src/a.ts", status: "modified", linesAdded: 3, linesRemoved: 1 },
      {
        path: "assets/logo.png",
        status: "added",
        linesAdded: 5000,
        linesRemoved: 0,
      },
      {
        path: "assets/demo.mp4",
        status: "added",
        linesAdded: 90000,
        linesRemoved: 0,
      },
    ];
    expect(computeDiffStats(files)).toEqual({
      filesChanged: 3,
      linesAdded: 3,
      linesRemoved: 1,
    });
  });
});
