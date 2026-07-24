import { describe, expect, it } from "vitest";
import {
  BRANCHES_FIRST_PAGE_SIZE,
  BRANCHES_PAGE_SIZE,
  branchPageSizeForOffset,
  computeNextBranchOffset,
  flattenBranchPages,
  type GithubBranchesPage,
} from "./branches";

const page = (
  branches: string[],
  hasMore: boolean,
  defaultBranch: string | null = null,
): GithubBranchesPage => ({ branches, hasMore, defaultBranch });

describe("branchPageSizeForOffset", () => {
  it("uses the first-page size for offset 0", () => {
    expect(branchPageSizeForOffset(0)).toBe(BRANCHES_FIRST_PAGE_SIZE);
    expect(branchPageSizeForOffset(50)).toBe(BRANCHES_PAGE_SIZE);
  });
});

describe("computeNextBranchOffset", () => {
  it("returns undefined when the last page has no more", () => {
    expect(
      computeNextBranchOffset(page(["a"], false), [page(["a"], false)]),
    ).toBe(undefined);
  });

  it("sums branch counts across pages for the next offset", () => {
    const pages = [page(["a", "b"], true), page(["c"], true)];
    expect(computeNextBranchOffset(pages[1], pages)).toBe(3);
  });
});

describe("flattenBranchPages", () => {
  it("returns empty defaults when there are no pages", () => {
    expect(flattenBranchPages(undefined)).toEqual({
      branches: [],
      defaultBranch: null,
    });
  });

  it("flattens branches and pulls defaultBranch from the first page", () => {
    const pages = [page(["a", "b"], true, "main"), page(["c"], false, "dev")];
    expect(flattenBranchPages(pages)).toEqual({
      branches: ["a", "b", "c"],
      defaultBranch: "main",
    });
  });
});
