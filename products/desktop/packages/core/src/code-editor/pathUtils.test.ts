import { describe, expect, it } from "vitest";
import { getRelativePath, isInsideRepoPath } from "./pathUtils";

describe("repo path containment", () => {
  it.each([
    { name: "file in the repo", abs: "/a/project/src/x.ts", inside: true },
    { name: "the repo root itself", abs: "/a/project", inside: true },
    {
      name: "sibling with a shared prefix",
      abs: "/a/project2/x.ts",
      inside: false,
    },
    { name: "unrelated path", abs: "/b/other/x.ts", inside: false },
    { name: "windows separator", abs: "/a/project\\src\\x.ts", inside: true },
  ])("$name", ({ abs, inside }) => {
    expect(isInsideRepoPath(abs, "/a/project")).toBe(inside);
  });

  it.each([null, undefined, ""])("treats %s repo path as outside", (repo) => {
    expect(isInsideRepoPath("/a/project/x.ts", repo)).toBe(false);
  });

  // A sibling directory used to slice into a bogus repo-relative path
  // ("2/logo.png"), which routed the read at the repo reader and failed.
  it("returns the absolute path for a sibling directory", () => {
    expect(getRelativePath("/a/project2/logo.png", "/a/project")).toBe(
      "/a/project2/logo.png",
    );
  });

  it("returns the repo-relative path for repo content", () => {
    expect(getRelativePath("/a/project/src/x.ts", "/a/project")).toBe(
      "src/x.ts",
    );
  });

  it("ignores a trailing separator on the repo path", () => {
    expect(getRelativePath("/a/project/src/x.ts", "/a/project/")).toBe(
      "src/x.ts",
    );
  });
});
