import { describe, expect, it } from "vitest";
import { resolveTaskPrUrls } from "./resolveTaskPrUrls";

const PR_1 = "https://github.com/org/repo/pull/1";
const PR_2 = "https://github.com/org/repo/pull/2";
const PR_3 = "https://github.com/other/repo/pull/3";

describe("resolveTaskPrUrls", () => {
  it.each([
    [
      "no sources",
      { cloudUrls: [], cachedUrls: [], currentBranchUrl: null },
      { primaryUrl: null, otherUrls: [] },
    ],
    [
      "cloud first entry is primary",
      { cloudUrls: [PR_1, PR_2], cachedUrls: [], currentBranchUrl: null },
      { primaryUrl: PR_1, otherUrls: [PR_2] },
    ],
    [
      "cached order wins over current branch PR (promotion sticks)",
      { cloudUrls: [], cachedUrls: [PR_1], currentBranchUrl: PR_2 },
      { primaryUrl: PR_1, otherUrls: [PR_2] },
    ],
    [
      "cached list is the fallback primary",
      { cloudUrls: [], cachedUrls: [PR_1, PR_2], currentBranchUrl: null },
      { primaryUrl: PR_1, otherUrls: [PR_2] },
    ],
    [
      "current branch PR is the last-resort primary",
      { cloudUrls: [], cachedUrls: [], currentBranchUrl: PR_2 },
      { primaryUrl: PR_2, otherUrls: [] },
    ],
    [
      "primary is excluded from others across sources",
      { cloudUrls: [PR_1], cachedUrls: [PR_1, PR_2], currentBranchUrl: PR_1 },
      { primaryUrl: PR_1, otherUrls: [PR_2] },
    ],
    [
      "dedupes across sources preserving cloud order",
      {
        cloudUrls: [PR_1, PR_2],
        cachedUrls: [PR_2, PR_3],
        currentBranchUrl: PR_3,
      },
      { primaryUrl: PR_1, otherUrls: [PR_2, PR_3] },
    ],
  ])("%s", (_name, input, expected) => {
    expect(resolveTaskPrUrls(input)).toEqual(expected);
  });
});
