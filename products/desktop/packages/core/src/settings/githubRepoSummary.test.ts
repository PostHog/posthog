import { describe, expect, it } from "vitest";
import {
  githubInstallationSettingsUrl,
  summarizeReposByOwner,
} from "./githubRepoSummary";

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
