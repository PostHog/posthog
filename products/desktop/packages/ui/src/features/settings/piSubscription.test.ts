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
  ...overrides,
});

describe("effectivePiSubscriptionProvider", () => {
  it.each([
    [
      "posthog billing uses the gateway",
      {
        modelAccess: "posthog-gateway" as const,
        subscription: subscription(),
        workspaceMode: "local" as const,
      },
      undefined,
    ],
    [
      "cloud tasks use the gateway",
      {
        modelAccess: "openai-codex" as const,
        subscription: subscription(),
        workspaceMode: "cloud" as const,
      },
      undefined,
    ],
    [
      "a signed-out ChatGPT subscription uses the gateway",
      {
        modelAccess: "openai-codex" as const,
        subscription: subscription({ loggedIn: false }),
        workspaceMode: "local" as const,
      },
      undefined,
    ],
    [
      "a disabled ChatGPT subscription uses the gateway",
      {
        modelAccess: "openai-codex" as const,
        subscription: subscription({ flagEnabled: false }),
        workspaceMode: "local" as const,
      },
      undefined,
    ],
    [
      "a local ChatGPT subscription uses Codex",
      {
        modelAccess: "openai-codex" as const,
        subscription: subscription(),
        workspaceMode: "worktree" as const,
      },
      "openai-codex",
    ],
  ])("%s", (_name, input, expected) => {
    expect(effectivePiSubscriptionProvider(input)).toBe(expected);
  });
});
