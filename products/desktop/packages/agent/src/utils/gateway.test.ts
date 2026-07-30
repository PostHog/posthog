import { describe, expect, it } from "vitest";
import {
  getLlmGatewayUrl,
  resolveAiProduct,
  resolveGatewayProduct,
  resolveGatewayTarget,
  resolveLlmGatewayUrl,
} from "./gateway";

describe("resolveGatewayProduct", () => {
  it.each([
    { isInternal: false, originProduct: undefined, expected: "posthog_code" },
    {
      isInternal: undefined,
      originProduct: undefined,
      expected: "posthog_code",
    },
    {
      isInternal: false,
      originProduct: "signal_report",
      expected: "signals",
    },
    {
      isInternal: true,
      originProduct: undefined,
      expected: "background_agents",
    },
    {
      isInternal: true,
      originProduct: "session_summaries",
      expected: "background_agents",
    },
    { isInternal: true, originProduct: "signal_report", expected: "signals" },
    {
      isInternal: false,
      originProduct: "signals_scout",
      expected: "signals",
    },
    {
      isInternal: false,
      originProduct: "posthog_ai",
      expected: "posthog_ai",
    },
    {
      isInternal: true,
      originProduct: "signals_scout",
      expected: "signals",
    },
    {
      isInternal: true,
      originProduct: "posthog_ai",
      expected: "posthog_ai",
    },
    {
      isInternal: false,
      originProduct: "support_reply",
      expected: "conversations",
    },
    {
      isInternal: true,
      originProduct: "support_reply",
      expected: "conversations",
    },
    {
      isInternal: true,
      originProduct: "loop",
      expected: "posthog_code",
    },
    {
      isInternal: false,
      originProduct: "loop",
      expected: "posthog_code",
    },
  ] as const)(
    "isInternal=$isInternal originProduct=$originProduct -> $expected",
    ({ isInternal, originProduct, expected }) => {
      expect(resolveGatewayProduct({ isInternal, originProduct })).toBe(
        expected,
      );
    },
  );
});

describe("resolveLlmGatewayUrl", () => {
  it("appends the product slug to an env-provided base URL", () => {
    expect(
      resolveLlmGatewayUrl(
        "https://gateway.dev.posthog.dev",
        "https://app.dev.posthog.dev",
        "slack_app",
      ),
    ).toBe("https://gateway.dev.posthog.dev/slack_app");
  });

  it("appends the product slug after a trailing slash on the env URL", () => {
    expect(
      resolveLlmGatewayUrl(
        "https://gateway.dev.posthog.dev/",
        "https://app.dev.posthog.dev",
        "posthog_code",
      ),
    ).toBe("https://gateway.dev.posthog.dev/posthog_code");
  });

  it("falls back to the region-aware default when no env URL is provided", () => {
    expect(
      resolveLlmGatewayUrl(
        undefined,
        "https://us.posthog.com",
        "background_agents",
      ),
    ).toBe("https://gateway.us.posthog.com/background_agents");
  });

  it("treats an empty string env URL as unset", () => {
    expect(resolveLlmGatewayUrl("", "https://eu.posthog.com", "signals")).toBe(
      "https://gateway.eu.posthog.com/signals",
    );
  });
});

describe("getLlmGatewayUrl", () => {
  it.each([
    {
      posthogHost: "https://us.posthog.com",
      expected: "https://gateway.us.posthog.com/posthog_code",
    },
    {
      posthogHost: "https://eu.posthog.com",
      expected: "https://gateway.eu.posthog.com/posthog_code",
    },
    {
      posthogHost: "https://app.dev.posthog.dev",
      expected: "https://gateway.dev.posthog.dev/posthog_code",
    },
    {
      posthogHost: "http://localhost:8000",
      expected: "http://localhost:3308/posthog_code",
    },
  ] as const)("$posthogHost -> $expected", ({ posthogHost, expected }) => {
    expect(getLlmGatewayUrl(posthogHost)).toBe(expected);
  });

  it("uses the PostHog AI product route when requested", () => {
    expect(getLlmGatewayUrl("http://localhost:8000", "posthog_ai")).toBe(
      "http://localhost:3308/posthog_ai",
    );
  });
});

describe("resolveLlmGatewayUrl (slugless)", () => {
  it("does not append the product slug", () => {
    expect(
      resolveLlmGatewayUrl(
        "https://gateway.us.posthog.com",
        "https://us.posthog.com",
        "signals",
        { slugless: true },
      ),
    ).toBe("https://gateway.us.posthog.com");
  });

  it("strips a trailing /v1 so callers can re-append their own path", () => {
    expect(
      resolveLlmGatewayUrl(
        "https://gateway.us.posthog.com/v1",
        "https://us.posthog.com",
        "signals",
        { slugless: true },
      ),
    ).toBe("https://gateway.us.posthog.com");
  });

  it("strips trailing slashes", () => {
    expect(
      resolveLlmGatewayUrl(
        "https://gateway.us.posthog.com/v1//",
        "https://us.posthog.com",
        "signals",
        { slugless: true },
      ),
    ).toBe("https://gateway.us.posthog.com");
  });

  it("falls back to the region-aware host when no override is set", () => {
    expect(
      resolveLlmGatewayUrl(undefined, "https://eu.posthog.com", "signals", {
        slugless: true,
      }),
    ).toBe("https://gateway.eu.posthog.com");
  });

  it("keeps appending the slug when not slugless", () => {
    expect(
      resolveLlmGatewayUrl(
        "https://gateway.us.posthog.com",
        "https://us.posthog.com",
        "signals",
      ),
    ).toBe("https://gateway.us.posthog.com/signals");
  });
});

describe("resolveGatewayTarget", () => {
  const GO = "https://ai-gateway.us.posthog.com";
  const PY_HOST = "https://us.posthog.com";
  const SIGNALS_ENV = {
    AI_GATEWAY_URL: GO,
    AI_GATEWAY_PRODUCTS: "signals_scout,signals_research",
  };

  it("routes a listed product to the Go gateway with no slug", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: PY_HOST,
        env: SIGNALS_ENV,
      }),
    ).toEqual({ baseUrl: GO, isAiGateway: true, aiProduct: "signals_scout" });
  });

  it("leaves an unlisted signals stage on the Python gateway", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "implementation",
        posthogHost: PY_HOST,
        env: SIGNALS_ENV,
      }),
    ).toEqual({
      baseUrl: "https://gateway.us.posthog.com/signals",
      isAiGateway: false,
      aiProduct: "signals_implementation",
    });
  });

  it.each(["posthog_code", "background_agents", "slack_app"] as const)(
    "leaves %s on the Python gateway while signals migrates",
    (product) => {
      const target = resolveGatewayTarget({
        product,
        posthogHost: PY_HOST,
        env: SIGNALS_ENV,
      });
      expect(target.isAiGateway).toBe(false);
      expect(target.baseUrl).toBe(`https://gateway.us.posthog.com/${product}`);
    },
  );

  it("stays on the Python gateway when no Go URL is set", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: PY_HOST,
        env: { AI_GATEWAY_PRODUCTS: "signals_scout" },
      }).isAiGateway,
    ).toBe(false);
  });

  it("stays on the Python gateway when the allowlist is empty", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: PY_HOST,
        env: { AI_GATEWAY_URL: GO },
      }).isAiGateway,
    ).toBe(false);
  });

  it("tolerates whitespace and blanks in the allowlist", () => {
    expect(
      resolveGatewayTarget({
        product: "signals",
        aiStage: "scout",
        posthogHost: PY_HOST,
        env: { AI_GATEWAY_URL: GO, AI_GATEWAY_PRODUCTS: " , signals_scout , " },
      }).isAiGateway,
    ).toBe(true);
  });

  it("honours an LLM_GATEWAY_URL override on the unrouted path", () => {
    expect(
      resolveGatewayTarget({
        product: "posthog_code",
        posthogHost: PY_HOST,
        env: {
          ...SIGNALS_ENV,
          LLM_GATEWAY_URL: "https://gateway.dev.posthog.dev",
        },
      }).baseUrl,
    ).toBe("https://gateway.dev.posthog.dev/posthog_code");
  });
});

describe("resolveAiProduct", () => {
  it.each([
    ["scout", "signals_scout"],
    ["research", "signals_research"],
    ["implementation", "signals_implementation"],
    ["repo_selection", "signals_repo_selection"],
  ])("maps the signals %s stage to %s", (aiStage, expected) => {
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
  });

  it.each([
    "posthog_code",
    "background_agents",
    "slack_app",
    "posthog_ai",
    "conversations",
  ] as const)("keeps %s unchanged", (product) => {
    expect(resolveAiProduct({ product })).toBe(product);
  });
});
