import { describe, expect, it } from "vitest";
import {
  buildPrOutput,
  mergePrUrls,
  promotePrUrl,
  readPrSummaries,
  readPrUrls,
} from "./pr-urls";

const A = "https://github.com/posthog/posthog/pull/1";
const B = "https://github.com/posthog/posthog/pull/2";
const C = "https://github.com/other/repo/pull/3";

describe("readPrUrls", () => {
  it.each([
    ["null output", null, []],
    ["undefined output", undefined, []],
    ["empty output", {}, []],
    ["legacy pr_url only", { pr_url: A }, [A]],
    ["pr_urls only", { pr_urls: [A, B] }, [A, B]],
    ["consistent pr_url and pr_urls", { pr_url: A, pr_urls: [A, B] }, [A, B]],
    [
      "old-writer pr_url diverging from pr_urls appends at end",
      { pr_url: C, pr_urls: [A, B] },
      [A, B, C],
    ],
    ["empty string pr_url ignored", { pr_url: "" }, []],
    [
      "non-string junk filtered from pr_urls",
      { pr_urls: [A, 42, null, "", B] },
      [A, B],
    ],
    ["duplicates collapsed", { pr_urls: [A, B, A] }, [A, B]],
    ["non-array pr_urls with pr_url", { pr_url: A, pr_urls: "junk" }, [A]],
  ])("%s", (_name, output, expected) => {
    expect(readPrUrls(output as Record<string, unknown> | null)).toEqual(
      expected,
    );
  });
});

describe("mergePrUrls", () => {
  it.each([
    ["no lists", [], []],
    ["single list", [[A, B]], [A, B]],
    [
      "earlier list wins on order",
      [
        [A, B],
        [C, A],
      ],
      [A, B, C],
    ],
    ["dedupes across lists", [[A], [A], [B]], [A, B]],
    ["empty lists ignored", [[], [A], []], [A]],
  ])("%s", (_name, lists, expected) => {
    expect(mergePrUrls(...(lists as string[][]))).toEqual(expected);
  });
});

describe("promotePrUrl", () => {
  it.each([
    ["moves an existing url to the front", [A, B, C], B, [B, A, C]],
    ["keeps an already-primary url in place", [A, B], A, [A, B]],
    ["adds a missing url at the front", [A, B], C, [C, A, B]],
    ["works on an empty list", [], A, [A]],
  ])("%s", (_name, urls, url, expected) => {
    expect(promotePrUrl(urls, url)).toEqual(expected);
  });
});

describe("readPrSummaries", () => {
  it.each([
    ["null output", null, {}],
    ["missing key", {}, {}],
    ["non-object pr_summaries", { pr_summaries: "junk" }, {}],
    ["array pr_summaries", { pr_summaries: [A] }, {}],
    [
      "keeps string entries, drops junk and empties",
      { pr_summaries: { [A]: "Fix login loop", [B]: 42, [C]: "" } },
      { [A]: "Fix login loop" },
    ],
  ])("%s", (_name, output, expected) => {
    expect(readPrSummaries(output as Record<string, unknown> | null)).toEqual(
      expected,
    );
  });
});

describe("buildPrOutput", () => {
  it("sets pr_url to the first entry and pr_urls to the full list", () => {
    expect(buildPrOutput({}, [A, B])).toEqual({ pr_url: A, pr_urls: [A, B] });
  });

  it("preserves foreign keys", () => {
    expect(buildPrOutput({ commit_sha: "abc", pr_url: B }, [A, B])).toEqual({
      commit_sha: "abc",
      pr_url: A,
      pr_urls: [A, B],
    });
  });

  it("drops stale pr keys when the list is empty", () => {
    expect(buildPrOutput({ commit_sha: "abc", pr_url: A }, [])).toEqual({
      commit_sha: "abc",
    });
  });

  it("dedupes and filters the provided list", () => {
    expect(buildPrOutput(null, [A, "", A, B])).toEqual({
      pr_url: A,
      pr_urls: [A, B],
    });
  });

  it("merges new summaries over existing ones", () => {
    const existing = { pr_summaries: { [A]: "Old label" } };
    expect(buildPrOutput(existing, [A, B], { [B]: "Fix login loop" })).toEqual({
      pr_url: A,
      pr_urls: [A, B],
      pr_summaries: { [A]: "Old label", [B]: "Fix login loop" },
    });
  });

  it("drops summaries for urls no longer in the list", () => {
    const existing = { pr_summaries: { [A]: "Old label", [C]: "Stale" } };
    expect(buildPrOutput(existing, [A])).toEqual({
      pr_url: A,
      pr_urls: [A],
      pr_summaries: { [A]: "Old label" },
    });
  });

  it("omits pr_summaries entirely when none apply", () => {
    expect(buildPrOutput({ pr_summaries: { [C]: "Stale" } }, [A])).toEqual({
      pr_url: A,
      pr_urls: [A],
    });
  });
});
