import { describe, expect, it } from "vitest";
import { parseFileHref } from "./fileHref";

describe("parseFileHref", () => {
  it("reads a repo-relative path", () => {
    expect(parseFileHref("src/App.tsx")).toEqual({
      path: "src/App.tsx",
      line: null,
    });
  });

  it("drops a leading current-directory marker", () => {
    expect(parseFileHref("./src/App.tsx")).toEqual({
      path: "src/App.tsx",
      line: null,
    });
  });

  it("reads an absolute path", () => {
    expect(parseFileHref("/repo/src/App.tsx")).toEqual({
      path: "/repo/src/App.tsx",
      line: null,
    });
  });

  it("reads a line suffix", () => {
    expect(parseFileHref("src/App.tsx:79")).toEqual({
      path: "src/App.tsx",
      line: 79,
    });
  });

  it("reads the first line of a range", () => {
    expect(parseFileHref("src/App.tsx:79-98")).toEqual({
      path: "src/App.tsx",
      line: 79,
    });
  });

  it.each([
    ["src/App.tsx#L79", { path: "src/App.tsx", line: 79 }],
    ["src/App.tsx#L79-L98", { path: "src/App.tsx", line: 79 }],
    ["src/App.tsx#L79-98", { path: "src/App.tsx", line: 79 }],
    ["README.md#installation", { path: "README.md", line: null }],
    ["docs/guide.md#usage-notes", { path: "docs/guide.md", line: null }],
  ])("takes the fragment off %s", (href, expected) => {
    expect(parseFileHref(href)).toEqual(expected);
  });

  it("reads a file URL", () => {
    expect(parseFileHref("file:///repo/src/My%20App.tsx")).toEqual({
      path: "/repo/src/My App.tsx",
      line: null,
    });
  });

  it("drops the slash a file URL puts before a Windows drive", () => {
    expect(parseFileHref("file:///C:/repo/App.tsx")).toEqual({
      path: "C:/repo/App.tsx",
      line: null,
    });
  });

  it.each([
    ["file:///repo/src/App.tsx#L12", { path: "/repo/src/App.tsx", line: 12 }],
    ["file:///repo/src/App.tsx:79", { path: "/repo/src/App.tsx", line: 79 }],
    ["file:///C:/repo/App.tsx#L12", { path: "C:/repo/App.tsx", line: 12 }],
    ["file:///repo/src/App%3A12", { path: "/repo/src/App:12", line: null }],
    ["file:///repo/src/App%23L12", { path: "/repo/src/App#L12", line: null }],
    ["file:///repo/src/App.tsx#top", { path: "/repo/src/App.tsx", line: null }],
    [
      "file:///repo/src/App.tsx#L12-L40",
      { path: "/repo/src/App.tsx", line: 12 },
    ],
  ])("reads %s", (href, expected) => {
    expect(parseFileHref(href)).toEqual(expected);
  });

  it("rejects a file URL on another host", () => {
    expect(parseFileHref("file://server/share/App.tsx")).toBeNull();
  });

  it.each([
    "https://posthog.com",
    "http://localhost:8000/x",
    "mailto:someone@posthog.com",
    "posthog-code://task/1",
    "evidence:insight/9pQx3",
    "chart:abc",
    "//example.com/App.tsx",
    "#section",
    "",
    undefined,
  ])("leaves %s to its existing handling", (href) => {
    expect(parseFileHref(href)).toBeNull();
  });
});
