import { describe, expect, it } from "vitest";
import {
  type ParsedGithubIssueUrl,
  parseGithubIssueUrl,
} from "./githubIssueUrl";

describe("parseGithubIssueUrl", () => {
  const accepts: Array<{
    name: string;
    input: string;
    expected: ParsedGithubIssueUrl;
  }> = [
    {
      name: "canonical issue URL",
      input: "https://github.com/PostHog/code/issues/1808",
      expected: {
        kind: "issue",
        owner: "PostHog",
        repo: "code",
        number: 1808,
        normalizedUrl: "https://github.com/PostHog/code/issues/1808",
      },
    },
    {
      name: "pull request URL",
      input: "https://github.com/PostHog/code/pull/1454",
      expected: {
        kind: "pr",
        owner: "PostHog",
        repo: "code",
        number: 1454,
        normalizedUrl: "https://github.com/PostHog/code/pull/1454",
      },
    },
    {
      name: "pull request URL with files tab suffix",
      input: "https://github.com/PostHog/code/pull/1454/files",
      expected: {
        kind: "pr",
        owner: "PostHog",
        repo: "code",
        number: 1454,
        normalizedUrl: "https://github.com/PostHog/code/pull/1454",
      },
    },
    {
      name: "surrounding whitespace",
      input: "  https://github.com/PostHog/code/issues/1808\n",
      expected: {
        kind: "issue",
        owner: "PostHog",
        repo: "code",
        number: 1808,
        normalizedUrl: "https://github.com/PostHog/code/issues/1808",
      },
    },
    {
      name: "fragment is stripped from normalized URL",
      input: "https://github.com/PostHog/code/issues/1808#issuecomment-123",
      expected: {
        kind: "issue",
        owner: "PostHog",
        repo: "code",
        number: 1808,
        normalizedUrl: "https://github.com/PostHog/code/issues/1808",
      },
    },
    {
      name: "query string is stripped from normalized URL",
      input: "https://github.com/PostHog/code/issues/1808?foo=bar",
      expected: {
        kind: "issue",
        owner: "PostHog",
        repo: "code",
        number: 1808,
        normalizedUrl: "https://github.com/PostHog/code/issues/1808",
      },
    },
    {
      name: "http scheme",
      input: "http://github.com/PostHog/code/issues/1",
      expected: {
        kind: "issue",
        owner: "PostHog",
        repo: "code",
        number: 1,
        normalizedUrl: "https://github.com/PostHog/code/issues/1",
      },
    },
  ];

  it.each(accepts)("accepts $name", ({ input, expected }) => {
    expect(parseGithubIssueUrl(input)).toEqual(expected);
  });

  const rejects: Array<{ name: string; input: string }> = [
    {
      name: "non-github host",
      input: "https://gitlab.com/PostHog/code/issues/1808",
    },
    { name: "non-URL text", input: "not a url" },
    { name: "empty string", input: "" },
    {
      name: "missing issue number",
      input: "https://github.com/PostHog/code/issues/",
    },
    {
      name: "missing PR number",
      input: "https://github.com/PostHog/code/pull/",
    },
    {
      name: "unknown path segment",
      input: "https://github.com/PostHog/code/blob/main/README.md",
    },
  ];

  it.each(rejects)("rejects $name", ({ input }) => {
    expect(parseGithubIssueUrl(input)).toBeNull();
  });
});
