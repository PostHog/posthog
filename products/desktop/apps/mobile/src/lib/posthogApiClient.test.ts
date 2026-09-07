import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authState: {
    cloudRegion: "us" as string | null,
    getCloudUrlFromRegion: vi.fn(() => "https://us.posthog.com"),
    oauthAccessToken: "access-token" as string | null,
    projectId: 123 as number | null,
    refreshAccessToken: vi.fn(async () => {}),
  },
  expoApplication: {
    nativeApplicationVersion: "1.2.3" as string | null,
  },
  expoConstants: {
    expoConfig: { version: "9.9.9" } as { version?: string } | null,
  },
  expoFetch: vi.fn(),
  instances: [] as Array<{
    apiHost: string;
    getAccessToken: () => Promise<string>;
    refreshAccessToken: () => Promise<string>;
    teamId: number | undefined;
    options: Record<string, unknown>;
    setTeamId: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("@posthog/api-client/posthog-client", () => ({
  PostHogAPIClient: class {
    setTeamId = vi.fn();

    constructor(
      apiHost: string,
      getAccessToken: () => Promise<string>,
      refreshAccessToken: () => Promise<string>,
      teamId: number | undefined,
      options: Record<string, unknown>,
    ) {
      mocks.instances.push({
        apiHost,
        getAccessToken,
        refreshAccessToken,
        teamId,
        options,
        setTeamId: this.setTeamId,
      });
    }
  },
}));

vi.mock("expo-application", () => ({
  get nativeApplicationVersion() {
    return mocks.expoApplication.nativeApplicationVersion;
  },
}));

vi.mock("expo-constants", () => ({
  default: {
    get expoConfig() {
      return mocks.expoConstants.expoConfig;
    },
  },
}));

vi.mock("expo/fetch", () => ({ fetch: mocks.expoFetch }));

vi.mock("@/features/auth", () => ({
  useAuthStore: {
    getState: () => mocks.authState,
  },
}));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  mocks.instances.length = 0;
  mocks.authState.cloudRegion = "us";
  mocks.authState.oauthAccessToken = "access-token";
  mocks.authState.projectId = 123;
  mocks.authState.getCloudUrlFromRegion.mockReturnValue(
    "https://us.posthog.com",
  );
  mocks.authState.refreshAccessToken.mockImplementation(async () => {});
  mocks.expoApplication.nativeApplicationVersion = "1.2.3";
  mocks.expoConstants.expoConfig = { version: "9.9.9" };
});

describe("createPostHogApiClient", () => {
  it("configures the shared client for the mobile host", async () => {
    const { createPostHogApiClient } = await import("./posthogApiClient");

    createPostHogApiClient();

    expect(mocks.instances).toHaveLength(1);
    expect(mocks.instances[0]).toMatchObject({
      apiHost: "https://us.posthog.com",
      teamId: 123,
      options: {
        appVersion: "1.2.3",
        githubConnectFrom: "posthog_mobile",
        userAgent: "posthog/mobile.hog.dev; version: 1.2.3",
      },
    });
  });

  it("converts URL inputs before calling Expo fetch", async () => {
    const { createPostHogApiClient } = await import("./posthogApiClient");
    createPostHogApiClient();
    const mobileFetch = mocks.instances[0]?.options.fetch as typeof fetch;
    const init = { method: "GET" };

    await mobileFetch(
      new URL("https://us.posthog.com/api/projects/2/tasks/"),
      init,
    );

    expect(mocks.expoFetch).toHaveBeenCalledWith(
      "https://us.posthog.com/api/projects/2/tasks/",
      init,
    );
  });

  it("falls back to the Expo config version", async () => {
    mocks.expoApplication.nativeApplicationVersion = null;
    mocks.expoConstants.expoConfig = { version: "4.5.6" };
    const { createPostHogApiClient } = await import("./posthogApiClient");

    createPostHogApiClient();

    expect(mocks.instances[0]?.options).toMatchObject({
      appVersion: "4.5.6",
      userAgent: "posthog/mobile.hog.dev; version: 4.5.6",
    });
  });

  it("returns the refreshed token from the current auth store state", async () => {
    mocks.authState.refreshAccessToken.mockImplementation(async () => {
      mocks.authState.oauthAccessToken = "refreshed-token";
    });
    const { createPostHogApiClient } = await import("./posthogApiClient");
    createPostHogApiClient();

    await expect(mocks.instances[0]?.refreshAccessToken()).resolves.toBe(
      "refreshed-token",
    );
    expect(mocks.authState.refreshAccessToken).toHaveBeenCalledOnce();
  });

  it("shares one refresh across concurrent client retries", async () => {
    let resolveRefresh: (() => void) | undefined;
    mocks.authState.refreshAccessToken.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveRefresh = () => {
            mocks.authState.oauthAccessToken = "refreshed-token";
            resolve();
          };
        }),
    );
    const { createPostHogApiClient } = await import("./posthogApiClient");
    createPostHogApiClient();

    const refreshes = [
      mocks.instances[0]?.refreshAccessToken(),
      mocks.instances[0]?.refreshAccessToken(),
    ];
    expect(mocks.authState.refreshAccessToken).toHaveBeenCalledOnce();
    resolveRefresh?.();

    await expect(Promise.all(refreshes)).resolves.toEqual([
      "refreshed-token",
      "refreshed-token",
    ]);
  });
});

describe("getPostHogApiClient", () => {
  it("reuses the regional client and updates its project", async () => {
    const { getPostHogApiClient } = await import("./posthogApiClient");

    const first = getPostHogApiClient();
    mocks.authState.projectId = 456;
    const second = getPostHogApiClient();

    expect(second).toBe(first);
    expect(mocks.instances).toHaveLength(1);
    expect(mocks.instances[0]?.setTeamId).toHaveBeenCalledWith(456);
  });

  it("creates a new client when the cloud region changes", async () => {
    const { getPostHogApiClient } = await import("./posthogApiClient");

    const first = getPostHogApiClient();
    mocks.authState.cloudRegion = "eu";
    mocks.authState.getCloudUrlFromRegion.mockReturnValue(
      "https://eu.posthog.com",
    );
    const second = getPostHogApiClient();

    expect(second).not.toBe(first);
    expect(mocks.instances.map(({ apiHost }) => apiHost)).toEqual([
      "https://us.posthog.com",
      "https://eu.posthog.com",
    ]);
  });
});
