import { beforeEach, describe, expect, it, vi } from "vitest";

const expoApplication = {
  nativeApplicationVersion: null as string | null,
};

const expoConstants = {
  expoConfig: null as { version?: string } | null,
};

vi.mock("posthog-react-native", () => ({
  usePostHog: () => null,
}));

vi.mock("expo-router", () => ({
  usePathname: () => "/",
  useSegments: () => [] as string[],
}));

vi.mock("expo-application", () => ({
  get nativeApplicationVersion() {
    return expoApplication.nativeApplicationVersion;
  },
}));

vi.mock("expo-constants", () => ({
  default: {
    get expoConfig() {
      return expoConstants.expoConfig;
    },
  },
}));

// posthog.ts imports the auth store and user query for useIdentifyUser. Their
// real modules transitively pull in native expo modules (expo-secure-store,
// expo-auth-session) that can't load under the node test environment, so mock
// them — these app-version tests don't exercise identification.
vi.mock("@/features/auth/stores/authStore", () => ({
  useAuthStore: () => false,
}));

vi.mock("@/features/auth/hooks/useUserQuery", () => ({
  useUserQuery: () => ({ data: undefined }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  expoApplication.nativeApplicationVersion = null;
  expoConstants.expoConfig = { version: "0.0.0-test" };
});

describe("getAppVersion", () => {
  it("prefers the native application version when present", async () => {
    expoApplication.nativeApplicationVersion = "9.8.7";
    expoConstants.expoConfig = { version: "0.0.0-test" };

    const { getAppVersion } = await import("./posthog");

    expect(getAppVersion()).toBe("9.8.7");
  });

  it("falls back to the Expo config version when no native version is available", async () => {
    expoApplication.nativeApplicationVersion = null;
    expoConstants.expoConfig = { version: "1.2.3" };

    const { getAppVersion } = await import("./posthog");

    expect(getAppVersion()).toBe("1.2.3");
  });

  it("returns null when neither source has a version", async () => {
    expoApplication.nativeApplicationVersion = null;
    expoConstants.expoConfig = null;

    const { getAppVersion } = await import("./posthog");

    expect(getAppVersion()).toBeNull();
  });
});

describe("registerPersistentSuperProperties", () => {
  it("registers team and app_version as super properties on the PostHog client", async () => {
    const register = vi.fn();
    const { registerPersistentSuperProperties } = await import("./posthog");

    registerPersistentSuperProperties({ register }, "1.2.3");

    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith({
      team: "posthog-code",
      app_version: "1.2.3",
    });
  });

  it("does nothing when the PostHog client is not yet available", async () => {
    const { registerPersistentSuperProperties } = await import("./posthog");

    expect(() =>
      registerPersistentSuperProperties(null, "1.2.3"),
    ).not.toThrow();
  });

  it("still registers team when no app version can be resolved", async () => {
    const register = vi.fn();
    const { registerPersistentSuperProperties } = await import("./posthog");

    registerPersistentSuperProperties({ register }, null);

    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith({ team: "posthog-code" });
  });

  it("resolves the version from getAppVersion when none is provided", async () => {
    expoApplication.nativeApplicationVersion = "4.5.6";
    const register = vi.fn();
    const { registerPersistentSuperProperties } = await import("./posthog");

    registerPersistentSuperProperties({ register });

    expect(register).toHaveBeenCalledWith({
      team: "posthog-code",
      app_version: "4.5.6",
    });
  });
});
