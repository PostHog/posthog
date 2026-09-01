import { beforeEach, describe, expect, it, vi } from "vitest";

const { registerAdapterSubscription } = vi.hoisted(() => ({
  registerAdapterSubscription: vi.fn(),
}));

vi.mock("@posthog/ui/shell/posthogAnalyticsImpl", () => ({
  registerAdapterSubscription,
}));

import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  effectiveModelAccess,
  registerSubscriptionAtBoot,
  subscriptionNeedsConnection,
} from "./adapterSubscription";

const status = (loggedIn: boolean) => ({ loggedIn });

describe("adapter subscription gating", () => {
  it.each([
    [
      "cloud tasks never bill the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "cloud" as const,
      },
      "posthog-gateway",
    ],
    [
      "not signed in falls back to the gateway",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: false,
        workspaceMode: "local" as const,
      },
      "posthog-gateway",
    ],
    [
      "flag off falls back to the gateway",
      {
        flagEnabled: false,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "local" as const,
      },
      "posthog-gateway",
    ],
    [
      "local on the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "local" as const,
      },
      "own-subscription",
    ],
    [
      "worktree on the subscription",
      {
        flagEnabled: true,
        subscriptionOn: true,
        loggedIn: true,
        workspaceMode: "worktree" as const,
      },
      "own-subscription",
    ],
  ])("%s", (_name, input, expected) => {
    expect(effectiveModelAccess(input)).toBe(expected);
  });

  it.each([
    [
      "unknown status while loading is not treated as signed out",
      { flagEnabled: true, subscriptionOn: true, status: undefined },
      false,
    ],
    [
      "confirmed signed out needs connection",
      { flagEnabled: true, subscriptionOn: true, status: status(false) },
      true,
    ],
    [
      "signed in does not need connection",
      { flagEnabled: true, subscriptionOn: true, status: status(true) },
      false,
    ],
    [
      "subscription off never needs connection",
      { flagEnabled: true, subscriptionOn: false, status: status(false) },
      false,
    ],
    [
      "flag off never needs connection",
      { flagEnabled: false, subscriptionOn: true, status: status(false) },
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
        () => Promise.resolve({ loggedIn: true }),
        true,
      );

      expect(registerAdapterSubscription).toHaveBeenLastCalledWith("claude", {
        access: "own-subscription",
        connected: true,
      });
    });
  });
});
