import { describe, expect, it } from "vitest";
import { billingRespawnNeeded } from "./sessionService";

type Case = {
  name: string;
  run: Parameters<typeof billingRespawnNeeded>[0];
  desired: Parameters<typeof billingRespawnNeeded>[1];
  expected: boolean;
};

describe("billingRespawnNeeded", () => {
  const cases: Case[] = [
    {
      name: "claude run switched from own-subscription to PostHog",
      run: { adapter: "claude", claudeModelAccess: "own-subscription" },
      desired: { claude: "posthog-gateway" },
      expected: true,
    },
    {
      name: "codex run reads its own model access, not claude's",
      run: { adapter: "codex", codexModelAccess: "own-subscription" },
      desired: { claude: "own-subscription", codex: "posthog-gateway" },
      expected: true,
    },
    {
      name: "run already matches its desired billing",
      run: { adapter: "claude", claudeModelAccess: "posthog-gateway" },
      desired: { claude: "posthog-gateway" },
      expected: false,
    },
    {
      name: "cloud run never switches billing",
      run: {
        isCloud: true,
        adapter: "claude",
        claudeModelAccess: "own-subscription",
      },
      desired: { claude: "posthog-gateway" },
      expected: false,
    },
    {
      name: "run without an adapter cannot switch",
      run: { claudeModelAccess: "own-subscription" },
      desired: { claude: "posthog-gateway" },
      expected: false,
    },
    {
      name: "run with no desired billing stays on what it spawned with",
      run: { adapter: "claude", claudeModelAccess: "own-subscription" },
      desired: undefined,
      expected: false,
    },
    {
      name: "desired billing that omits the run's adapter leaves it alone",
      run: { adapter: "claude", claudeModelAccess: "own-subscription" },
      desired: { codex: "posthog-gateway" },
      expected: false,
    },
  ];

  it.each(cases)("$name", ({ run, desired, expected }) => {
    expect(billingRespawnNeeded(run, desired)).toBe(expected);
  });
});
