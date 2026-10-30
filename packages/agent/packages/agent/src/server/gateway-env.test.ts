import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Logger } from "../utils/logger";
import { buildGatewayEnv } from "./gateway-env";

const ENV_KEYS = [
  "LLM_GATEWAY_URL",
  "AI_GATEWAY_URL",
  "AI_GATEWAY_PRODUCTS",
  "AI_GATEWAY_PRODUCT",
  "AI_GATEWAY_AI_STAGE",
  "AI_GATEWAY_TOKEN",
];

const config = {
  apiKey: "oauth-token",
  apiUrl: "https://us.posthog.com",
  projectId: 7,
};

function logger(): Logger {
  return {
    warn: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  } as never;
}

describe("buildGatewayEnv", () => {
  const saved: Record<string, string | undefined> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      saved[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (saved[key] === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = saved[key];
      }
    }
  });

  // Without this flag the Claude adapter keeps `@cf/` ids, which Go refuses.
  it.each([
    {
      route: "Go with a minted token",
      env: {
        AI_GATEWAY_URL: "https://ai-gateway.us.posthog.com/v1",
        AI_GATEWAY_PRODUCTS: "posthog_code",
        AI_GATEWAY_PRODUCT: "posthog_code",
        AI_GATEWAY_TOKEN: "phe_run",
      },
      expected: true,
    },
    {
      route: "Go without a minted token",
      env: {
        AI_GATEWAY_URL: "https://ai-gateway.us.posthog.com/v1",
        AI_GATEWAY_PRODUCTS: "posthog_code",
        AI_GATEWAY_PRODUCT: "posthog_code",
      },
      expected: false,
    },
    {
      route: "the legacy gateway",
      env: {
        LLM_GATEWAY_URL: "https://gateway.us.posthog.com",
        AI_GATEWAY_TOKEN: "phe_run",
      },
      expected: false,
    },
  ])("sets isAiGateway to $expected on $route", ({ env, expected }) => {
    Object.assign(process.env, env);
    const gatewayEnv = buildGatewayEnv(config, {}, logger());

    expect(gatewayEnv.isAiGateway).toBe(expected);
    expect(gatewayEnv.anthropicAuthToken).toBe(
      expected ? "phe_run" : "oauth-token",
    );
  });
});
