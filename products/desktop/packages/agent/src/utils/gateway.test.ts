import { describe, expect, it } from "vitest";
import {
  getLlmGatewayUrl,
  resolveGatewayProduct,
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
