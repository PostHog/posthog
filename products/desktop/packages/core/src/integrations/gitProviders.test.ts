import { describe, expect, it } from "vitest";
import {
  enabledGitProviders,
  gitProviderConnections,
  githubRepositories,
  gitlabRepository,
} from "./gitProviders";
import type { Integration } from "./selectors";

const github: Integration = {
  id: 1,
  kind: "github",
  display_name: "posthog",
};
const gitlab: Integration = {
  id: 2,
  kind: "gitlab",
  display_name: "PostHog / Desktop",
  config: {
    hostname: "https://gitlab.example.com/",
    path_with_namespace: "PostHog/Desktop",
    project_id: 42,
  },
};
const slack: Integration = { id: 3, kind: "slack" };

describe("gitProviders", () => {
  it.each([
    { gitlabEnabled: false, expected: ["github"] },
    { gitlabEnabled: true, expected: ["github", "gitlab"] },
  ])(
    "enables gitlab only behind the flag ($gitlabEnabled)",
    ({ gitlabEnabled, expected }) => {
      expect(enabledGitProviders({ gitlabEnabled })).toEqual(expected);
    },
  );

  it("keeps gitlab connections out of the list while the flag is off", () => {
    const connections = gitProviderConnections(
      [github, gitlab, slack],
      enabledGitProviders({ gitlabEnabled: false }),
    );
    expect(connections).toEqual([
      { provider: "github", integrationId: 1, label: "posthog" },
    ]);
  });

  it("lists both providers in one shape and ignores non-git integrations", () => {
    const connections = gitProviderConnections(
      [github, gitlab, slack],
      enabledGitProviders({ gitlabEnabled: true }),
    );
    expect(connections).toEqual([
      { provider: "github", integrationId: 1, label: "posthog" },
      { provider: "gitlab", integrationId: 2, label: "PostHog / Desktop" },
    ]);
  });

  it("derives the gitlab repository from the stored project path and host", () => {
    expect(gitlabRepository(gitlab)).toEqual({
      provider: "gitlab",
      integrationId: 2,
      fullName: "posthog/desktop",
      url: "https://gitlab.example.com/posthog/desktop",
    });
  });

  it.each([
    { config: undefined, expectedUrlPrefix: null },
    {
      config: { path_with_namespace: "group/project" },
      expectedUrlPrefix: "https://gitlab.com/group/project",
    },
  ])(
    "falls back to gitlab.com without a hostname and to nothing without a path",
    ({ config, expectedUrlPrefix }) => {
      const repository = gitlabRepository({ id: 9, kind: "gitlab", config });
      expect(repository?.url ?? null).toBe(expectedUrlPrefix);
    },
  );

  it("normalizes github names the way the backend keys them", () => {
    expect(githubRepositories(1, ["PostHog/PostHog", " ", "posthog/quill"])).toEqual([
      {
        provider: "github",
        integrationId: 1,
        fullName: "posthog/posthog",
        url: "https://github.com/posthog/posthog",
      },
      {
        provider: "github",
        integrationId: 1,
        fullName: "posthog/quill",
        url: "https://github.com/posthog/quill",
      },
    ]);
  });
});
