import { describe, expect, it, vi } from "vitest";
import { GithubConnectService } from "./githubConnectService";
import type { GithubConnectClient } from "./identifiers";

function makeClient(
  overrides: Partial<GithubConnectClient> = {},
): GithubConnectClient {
  return {
    startUserConnect: vi
      .fn()
      .mockResolvedValue({ install_url: "https://github.test/install" }),
    launchUrl: vi.fn().mockResolvedValue(undefined),
    startTeamFlow: vi.fn().mockResolvedValue({ success: true }),
    ...overrides,
  };
}

describe("GithubConnectService.connect", () => {
  it("runs the team flow for an eligible admin and reports flow team", async () => {
    const client = makeClient();
    const service = new GithubConnectService(client);

    const outcome = await service.connect({
      projectId: 7,
      isAdmin: true,
      projectHasTeamIntegration: false,
      cloudRegion: "us",
    });

    expect(outcome).toEqual({ flow: "team" });
    expect(client.startTeamFlow).toHaveBeenCalledWith({
      region: "us",
      projectId: 7,
    });
    expect(client.startUserConnect).not.toHaveBeenCalled();
    expect(client.launchUrl).not.toHaveBeenCalled();
  });

  it("falls through to the user flow when the team decision is false", async () => {
    const client = makeClient();
    const service = new GithubConnectService(client);

    const outcome = await service.connect({
      projectId: 7,
      isAdmin: false,
      projectHasTeamIntegration: false,
      cloudRegion: "us",
    });

    expect(outcome).toEqual({ flow: "user" });
    expect(client.startTeamFlow).not.toHaveBeenCalled();
    expect(client.startUserConnect).toHaveBeenCalledWith(7);
    expect(client.launchUrl).toHaveBeenCalledWith(
      "https://github.test/install",
    );
  });

  it("throws when the team flow reports failure", async () => {
    const client = makeClient({
      startTeamFlow: vi
        .fn()
        .mockResolvedValue({ success: false, error: "nope" }),
    });
    const service = new GithubConnectService(client);

    await expect(
      service.connect({
        projectId: 7,
        isAdmin: true,
        projectHasTeamIntegration: false,
        cloudRegion: "us",
      }),
    ).rejects.toThrow("nope");
  });

  it("throws when the user flow returns an empty install url", async () => {
    const client = makeClient({
      startUserConnect: vi.fn().mockResolvedValue({ install_url: "" }),
    });
    const service = new GithubConnectService(client);

    await expect(
      service.connect({
        projectId: 7,
        isAdmin: false,
        projectHasTeamIntegration: true,
        cloudRegion: "us",
      }),
    ).rejects.toThrow("GitHub connection did not return a URL");
    expect(client.launchUrl).not.toHaveBeenCalled();
  });
});

describe("GithubConnectService.connectUser", () => {
  it("always runs the user flow and launches the validated url", async () => {
    const client = makeClient();
    const service = new GithubConnectService(client);

    const outcome = await service.connectUser(42);

    expect(outcome).toEqual({ flow: "user" });
    expect(client.startUserConnect).toHaveBeenCalledWith(42);
    expect(client.launchUrl).toHaveBeenCalledWith(
      "https://github.test/install",
    );
    expect(client.startTeamFlow).not.toHaveBeenCalled();
  });
});
