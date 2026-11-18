import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Logger } from "../utils/logger";
import { buildPiProviderRoute } from "./gateway-env";

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

const properties = { task_id: "task-1", task_run_id: "run-1", ai_stage: null };

function logger(): Logger & { warn: ReturnType<typeof vi.fn> } {
  return {
    warn: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  } as never;
}

describe("buildPiProviderRoute", () => {
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

  function routeToGo(): void {
    process.env.AI_GATEWAY_URL = "https://ai-gateway.us.posthog.com/v1";
    process.env.AI_GATEWAY_PRODUCTS = "posthog_code";
    process.env.AI_GATEWAY_PRODUCT = "posthog_code";
  }

  it("uses the Go gateway with the scoped token when the worker minted one", () => {
    routeToGo();
    process.env.AI_GATEWAY_TOKEN = "phe_run";
    const route = buildPiProviderRoute(
      config,
      { taskId: "task-1", model: "claude-opus-5-5", properties },
      logger(),
    );

    expect(route.isAiGateway).toBe(true);
    expect(route.apiKey).toBe("phe_run");
    expect(route.baseUrl).toBe("https://ai-gateway.us.posthog.com");
    expect(route.model).toBe("claude-opus-5-5");
    expect(route.headers["X-PostHog-Session-Id"]).toBe("task-1");
    expect(JSON.parse(route.headers["X-PostHog-Properties"])).toMatchObject({
      task_id: "task-1",
      ai_product: "posthog_code",
      team_id: 7,
    });
    expect(
      Object.keys(route.headers).some((key) =>
        key.toLowerCase().startsWith("x-posthog-property-"),
      ),
    ).toBe(false);
  });

  it("sends GLM under the bare id on the Go gateway", () => {
    routeToGo();
    process.env.AI_GATEWAY_TOKEN = "phe_run";
    const route = buildPiProviderRoute(
      config,
      { model: "@cf/zai-org/glm-5.2", properties },
      logger(),
    );
    expect(route.model).toBe("zai-org/glm-5.2");
  });

  it("stays on the Python gateway with the run credential when no token was minted", () => {
    routeToGo();
    const log = logger();
    const route = buildPiProviderRoute(
      config,
      { model: "@cf/zai-org/glm-5.2", properties },
      log,
    );

    expect(route.isAiGateway).toBe(false);
    expect(route.apiKey).toBe("oauth-token");
    expect(route.baseUrl).toMatch(/\/posthog_code$/);
    expect(route.model).toBe("@cf/zai-org/glm-5.2");
    expect(route.headers["X-PostHog-Properties"]).toBeUndefined();
    expect(log.warn).toHaveBeenCalledOnce();
  });

  it("keeps the legacy route unchanged when the product is not routed", () => {
    process.env.LLM_GATEWAY_URL = "https://gateway.us.posthog.com";
    process.env.AI_GATEWAY_TOKEN = "phe_run";
    const route = buildPiProviderRoute(config, { properties }, logger());

    expect(route.isAiGateway).toBe(false);
    expect(route.apiKey).toBe("oauth-token");
    expect(route.baseUrl).toBe("https://gateway.us.posthog.com/posthog_code");
  });
});
