import { describe, expect, it, vi } from "vitest";
import { GitProviderService } from "./gitProviderService";
import type { GitProviderClient } from "./identifiers";
import type { Integration } from "./selectors";

const integrations: Integration[] = [
  { id: 1, kind: "github", display_name: "posthog" },
  { id: 2, kind: "github", display_name: "broken-org" },
  {
    id: 3,
    kind: "gitlab",
    display_name: "PostHog / Desktop",
    config: { path_with_namespace: "posthog/desktop" },
  },
  { id: 4, kind: "slack" },
];

function makeClient(): GitProviderClient {
  return {
    listGithubRepositories: vi.fn(async (integrationId: number) => {
      if (integrationId === 2) throw new Error("GitHub is down");
      return ["PostHog/posthog"];
    }),
  };
}

describe("GitProviderService", () => {
  it("merges every enabled provider into one sorted list and reports the failed connection", async () => {
    const client = makeClient();
    const service = new GitProviderService(client);

    const result = await service.listRepositories(integrations, [
      "github",
      "gitlab",
    ]);

    expect(result.connections.map((c) => c.integrationId)).toEqual([1, 2, 3]);
    expect(result.repositories).toEqual([
      {
        provider: "github",
        integrationId: 1,
        fullName: "posthog/posthog",
        url: "https://github.com/posthog/posthog",
      },
      {
        provider: "gitlab",
        integrationId: 3,
        fullName: "posthog/desktop",
        url: "https://gitlab.com/posthog/desktop",
      },
    ]);
    expect(result.failedConnections.map((c) => c.integrationId)).toEqual([2]);
    expect(client.listGithubRepositories).toHaveBeenCalledTimes(2);
  });

  it("never calls the network for gitlab and skips it when the provider is disabled", async () => {
    const client = makeClient();
    const service = new GitProviderService(client);

    const result = await service.listRepositories(integrations, ["github"]);

    expect(result.repositories.map((r) => r.provider)).toEqual(["github"]);
    expect(result.connections.some((c) => c.provider === "gitlab")).toBe(
      false,
    );
    expect(client.listGithubRepositories).not.toHaveBeenCalledWith(3);
  });
});
