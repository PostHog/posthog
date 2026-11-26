import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Logger } from "../utils/logger";
import { buildGatewayEnv, buildPiProviderRoute } from "./gateway-env";

const ENV_KEYS = [
  "AI_GATEWAY_URL",
  "AI_GATEWAY_PRODUCTS",
  "AI_GATEWAY_PRODUCT",
  "AI_GATEWAY_AI_STAGE",
  "AI_GATEWAY_TOKEN",
];

const config = {
  apiUrl: "https://us.posthog.com",
  projectId: 7,
};

const ROUTED_ENV = {
  AI_GATEWAY_URL: "https://ai-gateway.us.posthog.com/v1",
  AI_GATEWAY_PRODUCTS: "posthog_code",
  AI_GATEWAY_PRODUCT: "posthog_code",
  AI_GATEWAY_TOKEN: "phe_run",
};

function logger(): Logger {
  return {
    warn: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  } as never;
}

describe("gateway routes", () => {
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

  it("sends a routed run to Go under its minted token", () => {
    Object.assign(process.env, ROUTED_ENV);
    const gatewayEnv = buildGatewayEnv(config, {}, logger());

    expect(gatewayEnv.anthropicBaseUrl).toBe(
      "https://ai-gateway.us.posthog.com",
    );
    expect(gatewayEnv.openaiBaseUrl).toBe(
      "https://ai-gateway.us.posthog.com/v1",
    );
    expect(gatewayEnv.anthropicAuthToken).toBe("phe_run");
    expect(gatewayEnv.openaiApiKey).toBe("phe_run");
  });

  it.each([
    {
      route: "a routed run without a minted token",
      env: { ...ROUTED_ENV, AI_GATEWAY_TOKEN: undefined },
      message: "AI_GATEWAY_TOKEN is required for ai_product posthog_code",
    },
    {
      route: "an unlisted product",
      env: { ...ROUTED_ENV, AI_GATEWAY_PRODUCTS: "signals_scout" },
      message: 'AI_GATEWAY_PRODUCTS="signals_scout"',
    },
    {
      route: "a run with no gateway settings",
      env: {},
      message: "AI_GATEWAY_URL and AI_GATEWAY_PRODUCTS must route",
    },
  ])("refuses $route on both runtimes", ({ env, message }) => {
    for (const [key, value] of Object.entries(env)) {
      if (value !== undefined) process.env[key] = value;
    }

    expect(() => buildGatewayEnv(config, {}, logger())).toThrow(message);
    expect(() =>
      buildPiProviderRoute(config, { properties: {} }, logger()),
    ).toThrow(message);
  });

  it("attributes the run to the server's product over the internal default", () => {
    Object.assign(process.env, {
      ...ROUTED_ENV,
      AI_GATEWAY_PRODUCTS: "signals",
      AI_GATEWAY_PRODUCT: "",
    });
    const gatewayEnv = buildGatewayEnv(
      config,
      { gatewayProduct: "signals", isInternal: true },
      logger(),
    );

    const blob = JSON.parse(
      gatewayEnv.openaiCustomHeaders?.["X-PostHog-Properties"] ?? "{}",
    );
    expect(blob).toMatchObject({ ai_product: "signals", team_id: 7 });
  });
});
