import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLlmGatewayUrl } from "./gateway";
import {
  fallbackModelConfigs,
  gatewayBaseUrlForApi,
  resolveModelConfigs,
} from "./models";

describe("gatewayBaseUrlForApi", () => {
  it("routes openai-responses through the gateway's /v1 surface", () => {
    expect(gatewayBaseUrlForApi("openai-responses", "us")).toBe(
      `${getLlmGatewayUrl("us")}/v1`,
    );
  });

  it("routes every other api through the gateway's product root", () => {
    expect(gatewayBaseUrlForApi("anthropic-messages", "eu")).toBe(
      getLlmGatewayUrl("eu"),
    );
    expect(gatewayBaseUrlForApi("openai-completions", "dev")).toBe(
      getLlmGatewayUrl("dev"),
    );
  });

  it("routes models through an explicit gateway override", () => {
    expect(
      gatewayBaseUrlForApi("anthropic-messages", "us", "http://proxy/"),
    ).toBe("http://proxy");
    expect(gatewayBaseUrlForApi("openai-responses", "us", "http://proxy")).toBe(
      "http://proxy/v1",
    );
    expect(
      gatewayBaseUrlForApi("openai-responses", "us", "http://proxy/v1"),
    ).toBe("http://proxy/v1");
  });
});

describe("resolveModelConfigs", () => {
  const originalFetch = global.fetch;
  const originalOffline = process.env.PI_OFFLINE;
  const originalStatic = process.env.HARNESS_STATIC_MODELS;

  beforeEach(() => {
    delete process.env.PI_OFFLINE;
    delete process.env.HARNESS_STATIC_MODELS;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    if (originalOffline === undefined) {
      delete process.env.PI_OFFLINE;
    } else {
      process.env.PI_OFFLINE = originalOffline;
    }
    if (originalStatic === undefined) {
      delete process.env.HARNESS_STATIC_MODELS;
    } else {
      process.env.HARNESS_STATIC_MODELS = originalStatic;
    }
    vi.restoreAllMocks();
  });

  it("returns fallback models when PI_OFFLINE is set", async () => {
    process.env.PI_OFFLINE = "1";
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(configs).toEqual(fallbackModelConfigs("us"));
  });

  it("returns fallback models when HARNESS_STATIC_MODELS is set", async () => {
    process.env.HARNESS_STATIC_MODELS = "1";
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(configs).toEqual(fallbackModelConfigs("us"));
  });

  it("returns fallback models when the gateway request throws", async () => {
    global.fetch = vi
      .fn()
      .mockRejectedValue(new Error("network down")) as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(configs).toEqual(fallbackModelConfigs("us"));
  });

  it("returns fallback models when the gateway responds with a non-ok status", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
    }) as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(configs).toEqual(fallbackModelConfigs("us"));
  });

  it("returns fallback models when the gateway response has no data array", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    }) as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(configs).toEqual(fallbackModelConfigs("us"));
  });

  it("maps live gateway models into provider model configs, requesting the /v1/models endpoint", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [
          {
            id: "claude-opus-4-8",
            owned_by: "anthropic",
            display_name: "Claude Opus",
            context_window: 500000,
            supports_vision: true,
          },
          {
            id: "gpt-5.5",
            owned_by: "openai",
            context_window: 1000,
            supports_vision: false,
          },
          { id: "" },
        ],
      }),
    });
    global.fetch = fetchSpy as unknown as typeof fetch;

    const configs = await resolveModelConfigs("dev");

    expect(fetchSpy).toHaveBeenCalledWith(
      `${getLlmGatewayUrl("dev")}/v1/models`,
      expect.objectContaining({ signal: expect.anything() }),
    );
    expect(configs).toHaveLength(2);

    const opus = configs.find((model) => model.id === "claude-opus-4-8");
    expect(opus?.name).toBe("Claude Opus");
    expect(opus?.api).toBe("anthropic-messages");
    expect(opus?.input).toEqual(["text", "image"]);
    expect(opus?.contextWindow).toBe(500000);
    expect(opus?.compat).toEqual({ forceAdaptiveThinking: true });
    expect(opus?.thinkingLevelMap).toMatchObject({
      xhigh: "xhigh",
    });

    const gpt = configs.find((model) => model.id === "gpt-5.5");
    expect(gpt?.api).toBe("openai-responses");
    expect(gpt?.thinkingLevelMap).toMatchObject({
      off: "none",
      xhigh: "xhigh",
    });
    expect(gpt?.input).toEqual(["text"]);
    expect(gpt?.baseUrl).toBe(`${getLlmGatewayUrl("dev")}/v1`);
  });

  it("fetches models through an authenticated gateway override", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: [] }),
    });
    global.fetch = fetchSpy as unknown as typeof fetch;

    await resolveModelConfigs("us", "http://127.0.0.1:1234", "proxy-key");

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:1234/v1/models",
      expect.objectContaining({
        headers: { Authorization: "Bearer proxy-key" },
      }),
    );
  });

  it("falls back to the model id as the display name and default context window", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [{ id: "some-unknown-model" }],
      }),
    }) as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(configs).toHaveLength(1);
    expect(configs[0]?.name).toBe("some-unknown-model");
    expect(configs[0]?.contextWindow).toBe(200000);
    expect(configs[0]?.api).toBe("anthropic-messages");
    expect(configs[0]?.compat).toBeUndefined();
  });

  it("detects the cloudflare family from the model id prefix", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [{ id: "@cf/some/model" }],
      }),
    }) as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(configs[0]?.api).toBe("anthropic-messages");
    expect(configs[0]?.maxTokens).toBe(32000);
  });

  it("detects the openai family from the gpt- id prefix even without owned_by", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [{ id: "gpt-custom" }],
      }),
    }) as unknown as typeof fetch;

    const configs = await resolveModelConfigs("us");

    expect(configs[0]?.api).toBe("openai-responses");
    expect(configs[0]?.maxTokens).toBe(128000);
  });
});

describe("fallbackModelConfigs", () => {
  it("produces a non-empty, region-scoped model list", () => {
    const configs = fallbackModelConfigs("us");
    expect(configs.length).toBeGreaterThan(0);
    for (const config of configs) {
      expect(config.id).toBeTruthy();
      expect(config.cost).toEqual({
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
      });
    }
  });
});
