import { describe, expect, it } from "vitest";
import {
  type GatewayProduct,
  getAiGatewayUrl,
  modelIdForGatewayRoute,
  resolveAiGatewayBaseUrl,
  resolveAiProduct,
  resolveGatewayTarget,
} from "./gateway";
import routingCases from "./gateway-routing-cases.json";

describe("resolveAiGatewayBaseUrl", () => {
  it.each([
    ["an override as given", "https://ai-gateway.dev.posthog.dev"],
    ["a trailing /v1", "https://ai-gateway.dev.posthog.dev/v1"],
    ["trailing slashes", "https://ai-gateway.dev.posthog.dev/v1//"],
  ])("returns the base for %s", (_case, envUrl) => {
    expect(resolveAiGatewayBaseUrl(envUrl, "https://us.posthog.com")).toBe(
      "https://ai-gateway.dev.posthog.dev",
    );
  });

  it.each([
    [undefined, "https://eu.posthog.com", "https://ai-gateway.eu.posthog.com"],
    ["", "https://eu.posthog.com", "https://ai-gateway.eu.posthog.com"],
    [undefined, "http://localhost:8010", "http://localhost:8080"],
  ])(
    "derives the Go host when the override is %j",
    (envUrl, posthogHost, expected) => {
      expect(resolveAiGatewayBaseUrl(envUrl, posthogHost)).toBe(expected);
    },
  );
});

describe("getAiGatewayUrl", () => {
  it.each([
    {
      posthogHost: "https://us.posthog.com",
      expected: "https://ai-gateway.us.posthog.com",
    },
    {
      posthogHost: "https://eu.posthog.com",
      expected: "https://ai-gateway.eu.posthog.com",
    },
    {
      posthogHost: "https://app.dev.posthog.dev",
      expected: "https://ai-gateway.dev.posthog.dev",
    },
    {
      posthogHost: "http://localhost:8000",
      expected: "http://localhost:8080",
    },
  ] as const)("$posthogHost -> $expected", ({ posthogHost, expected }) => {
    expect(getAiGatewayUrl(posthogHost)).toBe(expected);
  });
});

describe("modelIdForGatewayRoute", () => {
  it.each([
    ["@cf/zai-org/glm-5.2", "zai-org/glm-5.2"],
    ["claude-opus-5-5", "claude-opus-5-5"],
    [undefined, undefined],
  ])("maps %s to %s", (model, expected) => {
    expect(modelIdForGatewayRoute(model)).toBe(expected);
  });
});

describe("resolveGatewayTarget", () => {
  const GO = "https://ai-gateway.us.posthog.com";
  const HOST = "https://us.posthog.com";
  const SIGNALS_ENV = {
    AI_GATEWAY_URL: GO,
    AI_GATEWAY_PRODUCTS: "signals_scout,signals_research",
  };

  it("routes a listed product to the Go gateway with no slug", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: HOST,
        env: SIGNALS_ENV,
      }),
    ).toEqual({
      baseUrl: GO,
      routed: true,
      aiProduct: "signals_scout",
      aiStage: "scout",
    });
  });

  it("does not route an unlisted signals stage", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "implementation",
        posthogHost: HOST,
        env: SIGNALS_ENV,
      }),
    ).toEqual({
      baseUrl: GO,
      routed: false,
      aiProduct: "signals_implementation",
      aiStage: "implementation",
    });
  });

  it.each([
    ["no Go URL is set", { AI_GATEWAY_PRODUCTS: "signals_scout" }, false],
    ["the allowlist is empty", { AI_GATEWAY_URL: GO }, false],
    [
      "the allowlist has whitespace and blanks",
      { AI_GATEWAY_URL: GO, AI_GATEWAY_PRODUCTS: " , signals_scout , " },
      true,
    ],
  ])("routes the scout stage when %s: %s", (_case, env, routed) => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: HOST,
        env,
      }).routed,
    ).toBe(routed);
  });

  it("routes a skill-qualified scout stage via the plain product entry", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout:web-analytics",
        posthogHost: HOST,
        env: SIGNALS_ENV,
      }),
    ).toEqual({
      baseUrl: GO,
      routed: true,
      aiProduct: "signals_scout",
      aiStage: "scout:web-analytics",
    });
  });

  it("routes only the listed skill via a skill-qualified entry", () => {
    const env = {
      AI_GATEWAY_URL: GO,
      AI_GATEWAY_PRODUCTS: "signals_scout:web-analytics",
    };
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout:web-analytics",
        posthogHost: HOST,
        env,
      }).routed,
    ).toBe(true);
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout:logs",
        posthogHost: HOST,
        env,
      }).routed,
    ).toBe(false);
  });

  it("does not let a skill-qualified entry route the bare scout stage", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: HOST,
        env: {
          AI_GATEWAY_URL: GO,
          AI_GATEWAY_PRODUCTS: "signals_scout:web-analytics",
        },
      }).routed,
    ).toBe(false);
  });

  it("prefers the worker's product and stage over the local derivation", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: null,
        posthogHost: HOST,
        env: {
          ...SIGNALS_ENV,
          AI_GATEWAY_PRODUCT: "signals_scout",
          AI_GATEWAY_AI_STAGE: "scout:web-analytics",
        },
      }),
    ).toEqual({
      baseUrl: GO,
      routed: true,
      aiProduct: "signals_scout",
      aiStage: "scout:web-analytics",
    });
  });

  // Without a disagreeing case the preference can be deleted with the suite green.
  it("uses the worker's product when the local derivation would pick another", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: HOST,
        env: { ...SIGNALS_ENV, AI_GATEWAY_PRODUCT: "signals_research" },
      }).aiProduct,
    ).toBe("signals_research");
  });

  it("uses the worker's stage when the caller fetched a different one", () => {
    // The stage decides the skill-qualified allowlist key and the blob's stage.
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout:logs",
        posthogHost: HOST,
        env: {
          AI_GATEWAY_URL: GO,
          AI_GATEWAY_PRODUCTS: "signals_scout:web-analytics",
          AI_GATEWAY_AI_STAGE: "scout:web-analytics",
        },
      }),
    ).toEqual({
      baseUrl: GO,
      routed: true,
      aiProduct: "signals_scout",
      aiStage: "scout:web-analytics",
    });
  });

  it("keeps the allowlist gate for a worker-provided product", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "summarization",
        posthogHost: HOST,
        env: { ...SIGNALS_ENV, AI_GATEWAY_PRODUCT: "signals_emission" },
      }).routed,
    ).toBe(false);
  });

  it("ignores blank worker product and stage values", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: HOST,
        env: {
          ...SIGNALS_ENV,
          AI_GATEWAY_PRODUCT: "  ",
          AI_GATEWAY_AI_STAGE: "",
        },
      }),
    ).toEqual({
      baseUrl: GO,
      routed: true,
      aiProduct: "signals_scout",
      aiStage: "scout",
    });
  });

  it("uses the Go URL the worker set over the host-derived one", () => {
    expect(
      resolveGatewayTarget({
        product: "review_hog",
        posthogHost: HOST,
        env: {
          AI_GATEWAY_URL: "https://ai-gateway.dev.posthog.dev/v1",
          AI_GATEWAY_PRODUCTS: "review_hog",
        },
      }).baseUrl,
    ).toBe("https://ai-gateway.dev.posthog.dev");
  });
});

describe("resolveAiProduct", () => {
  it.each([
    ["scout", "signals_scout"],
    ["research", "signals_research"],
    ["implementation", "signals_implementation"],
    ["repo_selection", "signals_repo_selection"],
    ["custom_agent", "signals_custom_agent"],
    ["inbox", "signals_inbox"],
    ["chat", "signals_chat"],
    ["scout_suggestions", "signals_scout_suggestions"],
  ])("maps the signals %s stage to %s", (aiStage, expected) => {
    expect(resolveAiProduct({ product: "signals", aiStage })).toBe(expected);
  });

  it.each([
    ["scout:web-analytics", "signals_scout"],
    ["scout:customer-analytics-billing-and-usage", "signals_scout"],
  ])("maps the skill-qualified %s stage to %s", (aiStage, expected) => {
    expect(resolveAiProduct({ product: "signals", aiStage })).toBe(expected);
  });

  it("leaves signals unsplit for an unrecognized stage", () => {
    expect(resolveAiProduct({ product: "signals", aiStage: "match" })).toBe(
      "signals",
    );
  });

  it("leaves signals unsplit when no stage is set", () => {
    expect(resolveAiProduct({ product: "signals", aiStage: null })).toBe(
      "signals",
    );
  });

  it("does not split a non-signals product that shares a stage name", () => {
    expect(
      resolveAiProduct({ product: "posthog_code", aiStage: "implementation" }),
    ).toBe("posthog_code");
    expect(
      resolveAiProduct({ product: "review_hog", aiStage: "resolution" }),
    ).toBe("review_hog");
  });

  it.each([
    "posthog_code",
    "background_agents",
    "slack_app",
    "posthog_ai",
    "conversations",
    "review_hog",
  ] as const)("keeps %s unchanged", (product) => {
    expect(resolveAiProduct({ product })).toBe(product);
  });
});

// Shared contract with the Python mirror (test_ai_gateway_token.py) — both suites
// consume gateway-routing-cases.json so the resolvers cannot drift independently.
describe("shared routing contract", () => {
  it.each(routingCases.resolve_ai_product)(
    "resolves $product/$ai_stage -> $expected",
    ({ product, ai_stage, expected }) => {
      expect(
        resolveAiProduct({
          product: product as GatewayProduct,
          aiStage: ai_stage,
        }),
      ).toBe(expected);
    },
  );

  it.each(routingCases.routed)(
    "routes $product/$ai_stage under [$allowlist] -> $expected",
    ({ product, ai_stage, allowlist, expected }) => {
      const target = resolveGatewayTarget({
        product: product as GatewayProduct,
        aiStage: ai_stage,
        posthogHost: "https://us.posthog.com",
        env: {
          AI_GATEWAY_URL: "https://ai-gateway.us.posthog.com",
          AI_GATEWAY_PRODUCTS: allowlist,
        },
      });
      expect(target.routed).toBe(expected);
    },
  );
});
