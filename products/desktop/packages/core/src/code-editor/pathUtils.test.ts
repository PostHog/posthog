import { describe, expect, it } from "vitest";
import { getRelativePath } from "./pathUtils";

describe("getRelativePath", () => {
  it("strips the repo root", () => {
    expect(getRelativePath("/repo/src/App.tsx", "/repo")).toBe("src/App.tsx");
  });

  it("tolerates a trailing slash on the repo root", () => {
    expect(getRelativePath("/repo/src/App.tsx", "/repo/")).toBe("src/App.tsx");
  });

  it("keeps a path outside the repo absolute", () => {
    expect(getRelativePath("/repo-two/src/App.tsx", "/repo")).toBe(
      "/repo-two/src/App.tsx",
    );
  });

  it("keeps an already relative path", () => {
    expect(getRelativePath("src/App.tsx", "/repo")).toBe("src/App.tsx");
  });

  it("returns the empty path for the root itself", () => {
    expect(getRelativePath("/repo", "/repo")).toBe("");
  });

  it("keeps the path when there is no repo", () => {
    expect(getRelativePath("/repo/src/App.tsx", null)).toBe(
      "/repo/src/App.tsx",
    );
  });
});
