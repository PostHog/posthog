import { describe, expect, it } from "vitest";
import {
  effectiveModelAccess,
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
});
