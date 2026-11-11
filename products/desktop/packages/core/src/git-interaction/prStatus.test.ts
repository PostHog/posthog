import { describe, expect, it } from "vitest";
import { parseGitlabMergeRequestUrl } from "./prStatus";

describe("parseGitlabMergeRequestUrl", () => {
  it.each([
    [
      "https://gitlab.com/acme/platform/api/-/merge_requests/4",
      { project: "acme/platform/api", iid: 4 },
    ],
    [
      "https://gitlab.com/acme/api/-/merge_requests/12/diffs",
      { project: "acme/api", iid: 12 },
    ],
    ["https://gitlab.example.com/acme/api/-/merge_requests/1", null],
    ["https://github.com/acme/api/pull/1", null],
    ["https://gitlab.com/acme/api/-/issues/1", null],
    ["not a url", null],
  ])("parses %s", (url, expected) => {
    expect(parseGitlabMergeRequestUrl(url)).toEqual(expected);
  });
});
