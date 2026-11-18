import { describe, expect, it } from "vitest";
import {
  desktopGatewayTokenHost,
  takeGatewayOverride,
} from "./gateway-override";

describe("takeGatewayOverride", () => {
  it("returns the override and removes both variables from the env", () => {
    const env: NodeJS.ProcessEnv = {
      POSTHOG_CODE_AI_GATEWAY_URL: "http://localhost:3308/v1",
      POSTHOG_CODE_AI_GATEWAY_TOKEN: "phe_dev",
      OTHER: "kept",
    };

    expect(takeGatewayOverride(env)).toEqual({
      url: "http://localhost:3308",
      token: "phe_dev",
    });
    expect(env).toEqual({ OTHER: "kept" });
  });

  it.each([
    [{ POSTHOG_CODE_AI_GATEWAY_URL: "http://localhost:3308" }],
    [{ POSTHOG_CODE_AI_GATEWAY_TOKEN: "phe_dev" }],
    [
      {
        POSTHOG_CODE_AI_GATEWAY_URL: "http://gateway.example",
        POSTHOG_CODE_AI_GATEWAY_TOKEN: "phe_dev",
      },
    ],
    [
      {
        POSTHOG_CODE_AI_GATEWAY_URL: "https://gateway.example",
        POSTHOG_CODE_AI_GATEWAY_TOKEN: "phe_dev",
      },
    ],
  ])(
    "ignores an incomplete, plain-http or unlisted override and still deletes it",
    (vars) => {
      const env: NodeJS.ProcessEnv = { ...vars };

      expect(takeGatewayOverride(env)).toBeNull();
      expect(env).toEqual({});
    },
  );
});

describe("desktopGatewayTokenHost", () => {
  it("enables the Go gateway and takes the override", () => {
    const env: NodeJS.ProcessEnv = {
      POSTHOG_CODE_AI_GATEWAY_URL: "http://localhost:3308",
      POSTHOG_CODE_AI_GATEWAY_TOKEN: "phe_dev",
    };

    expect(desktopGatewayTokenHost(env)).toEqual({
      goEnabled: true,
      override: { url: "http://localhost:3308", token: "phe_dev" },
    });
    expect(env).toEqual({});
  });

  it("enables the Go gateway without an override", () => {
    expect(desktopGatewayTokenHost({})).toEqual({
      goEnabled: true,
      override: null,
    });
  });
});
