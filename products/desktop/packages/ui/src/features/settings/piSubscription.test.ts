import { describe, expect, it } from "vitest";
import {
  effectivePiSubscriptionProvider,
  type PiSubscription,
} from "./piSubscription";

const subscription = (
  overrides: Partial<PiSubscription> = {},
): PiSubscription => ({
  flagEnabled: true,
  loggedIn: true,
  loginState: "logged-in",
  ...overrides,
});

describe("effectivePiSubscriptionProvider", () => {
  it.each([
    [
      "posthog pick uses the gateway even when logged in",
      {
        modelAccess: "posthog-gateway" as const,
        anthropic: subscription(),
        codex: subscription(),
        workspaceMode: "local" as const,
      },
      undefined,
    ],
    [
      "cloud tasks never bill the subscription",
      {
        modelAccess: "anthropic" as const,
        anthropic: subscription(),
        codex: subscription(),
        workspaceMode: "cloud" as const,
      },
      undefined,
    ],
    [
      "picked provider not logged in falls back to the gateway",
      {
        modelAccess: "anthropic" as const,
        anthropic: subscription({ loggedIn: false, loginState: "logged-out" }),
        codex: subscription(),
        workspaceMode: "local" as const,
      },
      undefined,
    ],
    [
      "picked provider's flag off falls back to the gateway",
      {
        modelAccess: "anthropic" as const,
        anthropic: subscription({ flagEnabled: false }),
        codex: subscription(),
        workspaceMode: "local" as const,
      },
      undefined,
    ],
    [
      "local on the picked anthropic subscription",
      {
        modelAccess: "anthropic" as const,
        anthropic: subscription(),
        codex: subscription({ loggedIn: false, loginState: "logged-out" }),
        workspaceMode: "local" as const,
      },
      "anthropic",
    ],
    [
      "worktree on the picked codex subscription",
      {
        modelAccess: "openai-codex" as const,
        anthropic: subscription({ loggedIn: false, loginState: "logged-out" }),
        codex: subscription(),
        workspaceMode: "worktree" as const,
      },
      "openai-codex",
    ],
  ])("%s", (_name, input, expected) => {
    expect(effectivePiSubscriptionProvider(input)).toBe(expected);
  });
});
