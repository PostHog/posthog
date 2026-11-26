import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { registerAdapterSubscription } = vi.hoisted(() => ({
  registerAdapterSubscription: vi.fn(),
}));

vi.mock("@posthog/ui/shell/posthogAnalyticsImpl", () => ({
  registerAdapterSubscription,
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));

vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: true }),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    agent: {
      codexSubscriptionStatus: { queryOptions: () => ({}) },
    },
  }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: { loginState: "logged-in" } }),
}));

import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  effectiveModelAccess,
  registerSubscriptionAtBoot,
  type SubscriptionStatus,
  subscriptionModelAccess,
  subscriptionNeedsConnection,
  useAdapterSubscription,
} from "./adapterSubscription";

const status = (loginState: "logged-in" | "logged-out" | "unknown") => ({
  loginState,
});

describe("adapter subscription gating", () => {
  it("offers Codex local and cloud subscriptions without feature flags", () => {
    useSettingsStore.setState({
      codexModelAccess: "own-subscription",
      codexCloudSubscriptionOn: true,
    });
    const { result } = renderHook(() => useAdapterSubscription("codex"));

    expect(result.current.flagEnabled).toBe(true);
    expect(result.current.cloudFlagEnabled).toBe(true);
    expect(subscriptionModelAccess(result.current, "local")).toBe(
      "own-subscription",
    );
    expect(subscriptionModelAccess(result.current, "cloud")).toBe(
      "own-subscription",
    );
  });

  it.each([
    [
      "cloud tasks never bill the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loginState: "logged-in" as const,
        workspaceMode: "cloud" as const,
      },
      "posthog-gateway",
    ],
    [
      "not signed in falls back to the gateway",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loginState: "logged-out" as const,
        workspaceMode: "local" as const,
      },
      "posthog-gateway",
    ],
    [
      "unknown status while loading falls back to the gateway",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loginState: "unknown" as const,
        workspaceMode: "local" as const,
      },
      "posthog-gateway",
    ],
    [
      "flag off falls back to the gateway",
      {
        flagEnabled: false,
        subscriptionOn: true,
        loginState: "logged-in" as const,
        workspaceMode: "local" as const,
      },
      "posthog-gateway",
    ],
    [
      "local on the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loginState: "logged-in" as const,
        workspaceMode: "local" as const,
      },
      "own-subscription",
    ],
    [
      "worktree on the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loginState: "logged-in" as const,
        workspaceMode: "worktree" as const,
      },
      "own-subscription",
    ],
  ])("%s", (_name, input, expected) => {
    expect(effectiveModelAccess(input)).toBe(expected);
  });

  it.each([
    ["subscription selected", true, true, "own-subscription"],
    ["rollout disabled after selection", true, false, "own-subscription"],
    ["gateway selected", false, true, "posthog-gateway"],
  ])(
    "cloud billing preserves intent: %s",
    (_name, cloudSubscriptionOn, cloudFlagEnabled, expected) => {
      expect(
        subscriptionModelAccess(
          {
            flagEnabled: false,
            subscriptionOn: false,
            cloudSubscriptionOn,
            cloudFlagEnabled,
            status: undefined,
            loggedIn: false,
            loginState: "unknown",
            needsConnection: false,
            setSubscriptionOn: () => {},
            setCloudSubscriptionOn: () => {},
          },
          "cloud",
        ),
      ).toBe(expected);
    },
  );

  it.each([
    [
      "unknown status while loading is not treated as signed out",
      { flagEnabled: true, subscriptionOn: true, status: undefined },
      false,
    ],
    [
      "confirmed signed out needs connection",
      { flagEnabled: true, subscriptionOn: true, status: status("logged-out") },
      true,
    ],
    [
      "signed in does not need connection",
      { flagEnabled: true, subscriptionOn: true, status: status("logged-in") },
      false,
    ],
    [
      "unknown status does not need connection",
      { flagEnabled: true, subscriptionOn: true, status: status("unknown") },
      false,
    ],
    [
      "subscription off never needs connection",
      {
        flagEnabled: true,
        subscriptionOn: false,
        status: status("logged-out"),
      },
      false,
    ],
    [
      "flag off never needs connection",
      {
        flagEnabled: false,
        subscriptionOn: true,
        status: status("logged-out"),
      },
      false,
    ],
  ])("%s", (_name, input, expected) => {
    expect(subscriptionNeedsConnection(input)).toBe(expected);
  });

  describe("registerSubscriptionAtBoot", () => {
    beforeEach(() => {
      registerAdapterSubscription.mockClear();
      useSettingsStore.setState({
        _hasHydrated: true,
        claudeModelAccess: "own-subscription",
      });
    });

    it("reports the access value even when the login check fails", async () => {
      await expect(
        registerSubscriptionAtBoot(
          "claude",
          () => Promise.reject(new Error("claude auth status timed out")),
          true,
        ),
      ).rejects.toThrow("claude auth status timed out");

      expect(registerAdapterSubscription).toHaveBeenCalledWith("claude", {
        access: "own-subscription",
        connected: false,
      });
    });

    it("reports the login state once the check answers", async () => {
      await registerSubscriptionAtBoot(
        "claude",
        () => Promise.resolve({ loginState: "logged-in" }),
        true,
      );

      expect(registerAdapterSubscription).toHaveBeenLastCalledWith("claude", {
        access: "own-subscription",
        connected: true,
      });
    });

    it("does not run the login check when the flag is off", async () => {
      const fetchStatus = vi.fn(
        (): Promise<SubscriptionStatus> =>
          Promise.resolve({ loginState: "logged-in" }),
      );
      await registerSubscriptionAtBoot("claude", fetchStatus, false);

      expect(fetchStatus).not.toHaveBeenCalled();
      expect(registerAdapterSubscription).toHaveBeenLastCalledWith("claude", {
        access: "posthog-gateway",
        connected: false,
      });
    });

    it("re-reads the setting after the probe so a toggle change is not stale", async () => {
      useSettingsStore.setState({
        _hasHydrated: true,
        claudeModelAccess: "own-subscription",
      });
      const fetchStatus = vi.fn((): Promise<SubscriptionStatus> => {
        useSettingsStore.setState({ claudeModelAccess: "posthog-gateway" });
        return Promise.resolve({ loginState: "logged-in" });
      });
      await registerSubscriptionAtBoot("claude", fetchStatus, true);

      expect(registerAdapterSubscription).toHaveBeenLastCalledWith("claude", {
        access: "posthog-gateway",
        connected: true,
      });
    });
  });
});
