import type { Api, Model } from "@earendil-works/pi-ai";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getLlmGatewayUrl } from "./gateway";
import { DEFAULT_MODEL, fallbackModelConfigs } from "./models";
import * as oauth from "./oauth";
import {
  buildPosthogProvider,
  POSTHOG_PROVIDER_NAME,
  resolvePosthogProvider,
} from "./provider";

function makeModel(
  overrides: Partial<Model<Api>> & { id: string },
): Model<Api> {
  return {
    name: overrides.id,
    api: "anthropic-messages",
    provider: POSTHOG_PROVIDER_NAME,
    baseUrl: "https://gateway.us.posthog.com/posthog_code",
    reasoning: true,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 200000,
    maxTokens: 64000,
    ...overrides,
  };
}

describe("buildPosthogProvider", () => {
  const models = fallbackModelConfigs("us");

  it("defaults the provider to the anthropic-messages gateway surface", () => {
    const config = buildPosthogProvider(models, { region: "us" });

    expect(config.api).toBe("anthropic-messages");
    expect(config.baseUrl).toBe(getLlmGatewayUrl("us"));
    expect(config.baseUrl).toBe("https://gateway.us.posthog.com/posthog_code");
  });

  it("uses the PostHog OAuth token as the gateway credential", () => {
    const config = buildPosthogProvider(models);

    expect(config.oauth?.name).toBe("PostHog");
    expect(
      config.oauth?.getApiKey({ access: "pha_abc", refresh: "r", expires: 0 }),
    ).toBe("pha_abc");
  });

  it("accepts a static api key that overrides OAuth for headless use", () => {
    const config = buildPosthogProvider(models, { apiKey: "pha_static" });
    expect(config.apiKey).toBe("pha_static");
  });

  it("routes every provider model through an explicit gateway override", () => {
    const config = buildPosthogProvider(models, {
      region: "us",
      apiKey: "proxy-key",
      baseUrl: "http://127.0.0.1:1234",
    });

    expect(config.baseUrl).toBe("http://127.0.0.1:1234");
    expect(
      (config.models ?? [])
        .filter((model) => model.api === "anthropic-messages")
        .every((model) => model.baseUrl === "http://127.0.0.1:1234"),
    ).toBe(true);
    expect(
      (config.models ?? [])
        .filter((model) => model.api === "openai-responses")
        .every((model) => model.baseUrl === "http://127.0.0.1:1234/v1"),
    ).toBe(true);
  });

  it("omits apiKey entirely when none is provided", () => {
    const config = buildPosthogProvider(models);
    expect(config.apiKey).toBeUndefined();
  });

  it("uses a stable provider name", () => {
    expect(POSTHOG_PROVIDER_NAME).toBe("posthog");
  });

  it("delegates login and refresh to the oauth module for the resolved region", async () => {
    const loginSpy = vi
      .spyOn(oauth, "loginPosthog")
      .mockResolvedValue({ access: "a", refresh: "r", expires: 1 });
    const refreshSpy = vi
      .spyOn(oauth, "refreshPosthog")
      .mockResolvedValue({ access: "a2", refresh: "r2", expires: 2 });

    const config = buildPosthogProvider(models, { region: "eu" });
    const callbacks = {
      onAuth: vi.fn(),
      onDeviceCode: vi.fn(),
      onPrompt: vi.fn(),
      onSelect: vi.fn(),
    };

    await config.oauth?.login(callbacks);
    expect(loginSpy).toHaveBeenCalledWith(callbacks, "eu");

    await config.oauth?.refreshToken({
      access: "old",
      refresh: "old-r",
      expires: 0,
    });
    expect(refreshSpy).toHaveBeenCalledWith("eu", {
      access: "old",
      refresh: "old-r",
      expires: 0,
    });

    loginSpy.mockRestore();
    refreshSpy.mockRestore();
  });
});

describe("oauth.modifyModels", () => {
  const models = fallbackModelConfigs("us");

  it("remaps this provider's anthropic-messages models to the credential's region gateway", () => {
    const config = buildPosthogProvider(models, { region: "us" });
    const runtimeModels = [
      makeModel({ id: "claude-opus-4-8", api: "anthropic-messages" }),
    ];

    const result = config.oauth?.modifyModels?.(runtimeModels, {
      access: "a",
      refresh: "r",
      expires: 0,
      region: "eu",
    });

    expect(result?.[0]?.baseUrl).toBe(getLlmGatewayUrl("eu"));
  });

  it("remaps this provider's openai-responses models to the region's /v1 surface", () => {
    const config = buildPosthogProvider(models, { region: "us" });
    const runtimeModels = [
      makeModel({
        id: "gpt-5.5",
        api: "openai-responses",
        baseUrl: `${getLlmGatewayUrl("us")}/v1`,
      }),
    ];

    const result = config.oauth?.modifyModels?.(runtimeModels, {
      access: "a",
      refresh: "r",
      expires: 0,
      region: "eu",
    });

    expect(result?.[0]?.baseUrl).toBe(`${getLlmGatewayUrl("eu")}/v1`);
  });

  it("keeps an explicit gateway override when OAuth credentials have another region", () => {
    const config = buildPosthogProvider(models, {
      region: "us",
      baseUrl: "http://127.0.0.1:1234",
    });
    const runtimeModels = [
      makeModel({ id: "claude-opus-4-8", api: "anthropic-messages" }),
    ];

    const result = config.oauth?.modifyModels?.(runtimeModels, {
      access: "a",
      refresh: "r",
      expires: 0,
      region: "eu",
    });

    expect(result?.[0]?.baseUrl).toBe("http://127.0.0.1:1234");
  });

  it("leaves other providers' models untouched", () => {
    const config = buildPosthogProvider(models, { region: "us" });
    const otherModel = makeModel({ id: "gpt-4o", provider: "openai" });

    const result = config.oauth?.modifyModels?.([otherModel], {
      access: "a",
      refresh: "r",
      expires: 0,
      region: "eu",
    });

    expect(result?.[0]?.baseUrl).toBe(otherModel.baseUrl);
  });

  it("falls back to the provider's configured region when credentials have none", () => {
    const config = buildPosthogProvider(models, { region: "eu" });
    const runtimeModels = [makeModel({ id: "claude-opus-4-8" })];

    const result = config.oauth?.modifyModels?.(runtimeModels, {
      access: "a",
      refresh: "r",
      expires: 0,
    });

    expect(result?.[0]?.baseUrl).toBe(getLlmGatewayUrl("eu"));
  });
});

describe("resolvePosthogProvider", () => {
  const originalOffline = process.env.PI_OFFLINE;

  beforeEach(() => {
    process.env.PI_OFFLINE = "1";
  });

  afterEach(() => {
    if (originalOffline === undefined) {
      delete process.env.PI_OFFLINE;
    } else {
      process.env.PI_OFFLINE = originalOffline;
    }
  });

  it("resolves a full provider config using fallback models when offline", async () => {
    const config = await resolvePosthogProvider({ region: "us" });
    expect(config.name).toBe("PostHog");
    expect(config.models?.length).toBeGreaterThan(0);
    expect(config.baseUrl).toBe(getLlmGatewayUrl("us"));
  });

  it("defaults the region when none is provided", async () => {
    delete process.env.POSTHOG_REGION;
    const config = await resolvePosthogProvider();
    expect(config.baseUrl).toBe(getLlmGatewayUrl("us"));
  });
});

describe("model classification", () => {
  const byId = (region: "us" | "eu" | "dev") =>
    new Map(fallbackModelConfigs(region).map((model) => [model.id, model]));

  it("routes Claude models through anthropic-messages on the product base", () => {
    const model = byId("us").get(DEFAULT_MODEL);
    expect(model?.api).toBe("anthropic-messages");
    expect(model?.baseUrl).toBeUndefined();
  });

  it("routes OpenAI + codex models through openai-responses on the /v1 surface", () => {
    const models = byId("us");
    for (const id of ["gpt-5.5", "gpt-5.4", "gpt-5.3-codex"]) {
      const model = models.get(id);
      expect(model, id).toBeDefined();
      expect(model?.api).toBe("openai-responses");
      expect(model?.baseUrl).toBe(
        "https://gateway.us.posthog.com/posthog_code/v1",
      );
    }
  });

  it("exposes the GLM model via the anthropic-messages surface", () => {
    const glm = byId("us").get("@cf/zai-org/glm-5.2");
    expect(glm).toBeDefined();
    expect(glm?.api).toBe("anthropic-messages");
    expect(glm?.input).toEqual(["text"]);
  });

  it("points OpenAI models at the region-specific gateway", () => {
    const eu = byId("eu").get("gpt-5.5");
    expect(eu?.baseUrl).toBe("https://gateway.eu.posthog.com/posthog_code/v1");
  });
});
