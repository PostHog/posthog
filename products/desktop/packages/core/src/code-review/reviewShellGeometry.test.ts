import { describe, expect, it } from "vitest";
import {
  buildItemIndex,
  getDeferredMessage,
  splitFilePath,
  sumHunkStats,
} from "./reviewShellGeometry";

describe("splitFilePath", () => {
  it("splits a nested path into dir and file", () => {
    expect(splitFilePath("src/a/b/File.ts")).toEqual({
      dirPath: "src/a/b/",
      fileName: "File.ts",
    });
  });

  it("returns empty dir for a bare filename", () => {
    expect(splitFilePath("File.ts")).toEqual({
      dirPath: "",
      fileName: "File.ts",
    });
  });
});

describe("sumHunkStats", () => {
  it("sums addition and deletion lines across hunks", () => {
    const hunks = [
      { additionLines: 3, deletionLines: 1 },
      { additionLines: 2, deletionLines: 4 },
    ] as Parameters<typeof sumHunkStats>[0];
    expect(sumHunkStats(hunks)).toEqual({ additions: 5, deletions: 5 });
  });

  it("returns zeros for no hunks", () => {
    expect(sumHunkStats([])).toEqual({ additions: 0, deletions: 0 });
  });
});

describe("buildItemIndex", () => {
  it("maps scrollKey to index, skipping items without a key", () => {
    const index = buildItemIndex([{ scrollKey: "a" }, {}, { scrollKey: "b" }]);
    expect(index.get("a")).toBe(0);
    expect(index.get("b")).toBe(2);
    expect(index.size).toBe(2);
  });
});

describe("getDeferredMessage", () => {
  it("returns the line-limit message", () => {
    expect(getDeferredMessage("line-limit")).toContain("5,000-line");
  });

  it("returns the unavailable message", () => {
    expect(getDeferredMessage("unavailable")).toBe("Unable to load diff.");
  });

  it("returns the binary message", () => {
    expect(getDeferredMessage("binary")).toBe("Binary file not shown.");
  });
});
