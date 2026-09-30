import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  classifyPatchLine,
  fileStatusLabel,
  parsePatch,
  prFilesUrl,
  reviewErrorMessage,
  splitPath,
  taskPrUrl,
} from "./review";

describe("classifyPatchLine", () => {
  it.each([
    ["@@ -1,3 +1,4 @@ function main() {", "hunk"],
    ["+const added = true;", "add"],
    ["+++ looks like a header but is an added line", "add"],
    ["-const removed = true;", "del"],
    ["--- looks like a header but is a removed line", "del"],
    ["\\ No newline at end of file", "meta"],
    [" unchanged line", "context"],
    ["", "context"],
  ] as const)("classifies %j as %s", (line, kind) => {
    expect(classifyPatchLine(line)).toBe(kind);
  });
});

describe("parsePatch", () => {
  it("returns no lines for an empty patch", () => {
    expect(parsePatch("")).toEqual([]);
  });

  it("splits lines, drops the trailing newline, and keeps blank context", () => {
    expect(parsePatch("@@ -1,2 +1,2 @@\r\n-a\r\n+b\r\n\r\n c\n")).toEqual([
      { kind: "hunk", text: "@@ -1,2 +1,2 @@" },
      { kind: "del", text: "-a" },
      { kind: "add", text: "+b" },
      { kind: "context", text: "" },
      { kind: "context", text: " c" },
    ]);
  });
});

describe("splitPath", () => {
  it("splits the directory from the basename", () => {
    expect(splitPath("src/lib/queries.ts")).toEqual({
      dir: "src/lib/",
      base: "queries.ts",
    });
  });

  it("returns an empty directory for a root file", () => {
    expect(splitPath("README.md")).toEqual({ dir: "", base: "README.md" });
  });
});

describe("fileStatusLabel", () => {
  it("maps GitHub statuses and capitalizes unknown ones", () => {
    expect(fileStatusLabel("removed")).toBe("Deleted");
    expect(fileStatusLabel("renamed")).toBe("Renamed");
    expect(fileStatusLabel("retyped")).toBe("Retyped");
  });
});

describe("taskPrUrl", () => {
  const withOutput = (output: Record<string, unknown> | null) =>
    ({ latest_run: { output } }) as unknown as Task;

  it("reads pr_url from the latest run", () => {
    expect(
      taskPrUrl(withOutput({ pr_url: "https://github.com/o/r/pull/1" })),
    ).toBe("https://github.com/o/r/pull/1");
  });

  it("returns null without a usable pr_url", () => {
    expect(taskPrUrl(undefined)).toBeNull();
    expect(taskPrUrl({} as Task)).toBeNull();
    expect(taskPrUrl(withOutput(null))).toBeNull();
    expect(taskPrUrl(withOutput({ pr_url: "" }))).toBeNull();
    expect(taskPrUrl(withOutput({ pr_url: 12 }))).toBeNull();
  });
});

describe("prFilesUrl", () => {
  it("points at the files tab", () => {
    expect(prFilesUrl("https://github.com/o/r/pull/1")).toBe(
      "https://github.com/o/r/pull/1/files",
    );
    expect(prFilesUrl("https://github.com/o/r/pull/1/")).toBe(
      "https://github.com/o/r/pull/1/files",
    );
  });
});

describe("reviewErrorMessage", () => {
  it("uses the API detail when there is one", () => {
    const error = Object.assign(new Error("Failed request: [400]"), {
      body: { detail: "Connect GitHub in PostHog to load the review." },
    });
    expect(reviewErrorMessage(error)).toBe(
      "Connect GitHub in PostHog to load the review.",
    );
  });

  it("falls back for network and unexpected errors", () => {
    expect(reviewErrorMessage(new Error("Network request failed"))).toBe(
      "Could not load this pull request.",
    );
    expect(reviewErrorMessage({ body: { detail: "" } })).toBe(
      "Could not load this pull request.",
    );
    expect(reviewErrorMessage(null)).toBe("Could not load this pull request.");
  });
});
