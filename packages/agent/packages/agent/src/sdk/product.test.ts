import { describe, expect, expectTypeOf, it, vi } from "vitest";
import { z } from "zod";
import {
  type AgentSessionConfiguration,
  buildPullRequestFooter,
  defineProduct,
  type ProductLaunchConfiguration,
} from "./product";

function launch(
  launchOptions: Record<string, unknown> = {},
): ProductLaunchConfiguration {
  return { taskId: "task-1", runId: "run-1", launchOptions };
}

function session(
  launchOptions: Record<string, unknown>,
): AgentSessionConfiguration {
  return {
    launch: launch(launchOptions),
    services: { sendReply: vi.fn().mockResolvedValue(undefined) },
  };
}

describe("defineProduct", () => {
  it("passes parsed launch options to the session without changing the input", () => {
    const raw = { topic: "  Promises  ", unrelated: true };
    const input = session(raw);
    const product = defineProduct({
      id: "tutor",
      launchOptionsSchema: z.object({
        topic: z.string().trim(),
        level: z.number().default(1),
      }),
      configureSession({ launch: { launchOptions } }) {
        expectTypeOf(launchOptions).toEqualTypeOf<
          Readonly<{ topic: string; level: number }>
        >();
        return {
          identityInstructions: `${launchOptions.topic}, level ${launchOptions.level}`,
        };
      },
    });

    expect(product.configureSession(input)).toEqual({
      identityInstructions: "Promises, level 1",
    });
    expect(input.launch.launchOptions).toBe(raw);
    expect(raw).toEqual({ topic: "  Promises  ", unrelated: true });
  });

  it("rejects invalid launch options before the product runs", () => {
    const configureSession = vi.fn(() => ({}));
    const product = defineProduct({
      id: "tutor",
      launchOptionsSchema: z.object({ topic: z.string() }),
      configureSession,
    });

    expect(() => product.configureSession(session({}))).toThrow();
    expect(configureSession).not.toHaveBeenCalled();
  });
});

describe("buildPullRequestFooter", () => {
  it.each([
    [
      "desktop",
      {},
      {},
      "*Created with [PostHog Desktop](https://posthog.com/desktop?ref=pr)*",
    ],
    [
      "mobile overrides automated",
      { client_platform: "mobile" },
      { automated: true },
      "*Created with [PostHog Mobile](https://posthog.com?ref=pr)*",
    ],
    [
      "automated with an inbox report",
      {},
      {
        automated: true,
        source: { label: "inbox report", url: "https://example.com/r" },
      },
      "*Created with [PostHog](https://posthog.com?ref=pr) from an [inbox report](https://example.com/r)*",
    ],
    [
      "Slack thread",
      {},
      {
        automated: true,
        source: { label: "Slack thread", url: "https://example.com/t" },
      },
      "*Created with [PostHog](https://posthog.com?ref=pr) from a [Slack thread](https://example.com/t)*",
    ],
  ] as const)("formats the %s footer", (_name, options, footer, expected) => {
    expect(buildPullRequestFooter(launch(options), footer)).toBe(expected);
  });

  it("credits PostHog for a task from the web chat", () => {
    const webLaunch = { ...launch(), clientProvenance: "posthog_web" };
    const source = { label: "PostHog AI chat", url: "https://example.com/c" };

    expect(buildPullRequestFooter(webLaunch, { source })).toBe(
      "*Created with [PostHog](https://posthog.com?ref=pr) from a [PostHog AI chat](https://example.com/c)*",
    );
  });
});
