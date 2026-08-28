import { describe, expect, it } from "vitest";
import {
  describeGithubRepoAccess,
  formatGithubAccountLabel,
  formatRepoPreview,
  githubInstallationSettingsUrl,
  summarizeReposByOwner,
} from "./githubRepoSummary";

describe("describeGithubRepoAccess", () => {
  it.each([
    [
      "all with total",
      { selection: "all", total: 712, repos: ["a"], accountLabel: "PostHog" },
      { kind: "all", label: "All repositories in PostHog (712)" },
    ],
    [
      "all without total",
      { selection: "all", total: null, repos: [], accountLabel: "PostHog" },
      { kind: "all", label: "All repositories in PostHog" },
    ],
    [
      "selected repos",
      { selection: "selected", total: 2, repos: ["a/b", "a/c"] },
      { kind: "selected", label: "2 selected repositories" },
    ],
    [
      "single selected repo",
      { selection: "selected", total: 1, repos: ["a/b"] },
      { kind: "selected", label: "1 selected repository" },
    ],
    [
      "no repos",
      { selection: "selected", total: 0, repos: [] },
      { kind: "empty", label: "No repositories accessible" },
    ],
    [
      "unknown selection",
      { selection: null, total: null, repos: ["a/b", "a/c", "a/d"] },
      { kind: "unknown", label: "3 repositories accessible" },
    ],
  ])("%s", (_name, input, expected) => {
    expect(describeGithubRepoAccess(input)).toEqual(expected);
  });
});

describe("formatGithubAccountLabel", () => {
  it.each([
    ["real name", { name: "PostHog", type: "Organization" }, "PostHog"],
    ["blank name", { name: "  ", type: null }, "GitHub installation 152736578"],
    [
      "numeric placeholder",
      { name: "152736578", type: null },
      "GitHub installation 152736578",
    ],
    ["missing account", null, "GitHub installation 152736578"],
  ])("%s", (_name, account, expected) => {
    expect(formatGithubAccountLabel(account, "152736578")).toBe(expected);
  });
});

describe("formatRepoPreview", () => {
  it.each([
    [["a/b"], "a/b"],
    [["a/b", "a/c", "a/d"], "a/b, a/c, a/d"],
    [["a/b", "a/c", "a/d", "a/e", "a/f"], "a/b, a/c, a/d and 2 more"],
  ])("%j", (repos, expected) => {
    expect(formatRepoPreview(repos)).toBe(expected);
  });
});

describe("summarizeReposByOwner", () => {
  it("counts repos per owner and sorts by count desc then owner asc", () => {
    const result = summarizeReposByOwner([
      "acme/a",
      "acme/b",
      "beta/x",
      "acme/c",
      "beta/y",
    ]);
    expect(result).toEqual([
      { owner: "acme", count: 3 },
      { owner: "beta", count: 2 },
    ]);
  });

  it("treats a repo without a slash as its own owner", () => {
    expect(summarizeReposByOwner(["solo"])).toEqual([
      { owner: "solo", count: 1 },
    ]);
  });
});

describe("githubInstallationSettingsUrl", () => {
  it("links organization installs to the app page (org settings are owner-only)", () => {
    expect(
      githubInstallationSettingsUrl({
        installation_id: 42,
        account: { type: "Organization", name: "acme" },
      }),
    ).toBe("https://github.com/apps/posthog");
  });

  it("matches the organization account type case-insensitively", () => {
    expect(
      githubInstallationSettingsUrl({
        installation_id: 42,
        account: { type: "organization", name: "acme" },
      }),
    ).toBe("https://github.com/apps/posthog");
  });

  it("builds a user installation URL otherwise", () => {
    expect(
      githubInstallationSettingsUrl({
        installation_id: 7,
        account: { type: "User", name: "jane" },
      }),
    ).toBe("https://github.com/settings/installations/7");
  });
});
