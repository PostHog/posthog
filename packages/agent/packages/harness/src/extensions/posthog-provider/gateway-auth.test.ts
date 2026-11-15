import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import { getLlmGatewayUrl } from "./gateway";
import { resolveGatewayAuth, tryResolveGatewayAuth } from "./gateway-auth";

function fakeCtx(apiKey: string | undefined): ExtensionContext {
  return {
    modelRegistry: {
      getApiKeyForProvider: vi.fn().mockResolvedValue(apiKey),
    },
  } as unknown as ExtensionContext;
}

describe("resolveGatewayAuth", () => {
  it("uses a static apiKey option over the model registry", async () => {
    const auth = await resolveGatewayAuth(
      { region: "us", apiKey: "pha_static" },
      fakeCtx("pha_from_registry"),
    );
    expect(auth).toEqual({
      baseUrl: getLlmGatewayUrl("us"),
      apiKey: "pha_static",
      headers: {},
    });
  });

  it("uses an explicit gateway override and carries its attribution headers", async () => {
    const auth = await resolveGatewayAuth(
      {
        region: "us",
        apiKey: "proxy-key",
        baseUrl: "http://127.0.0.1:1234",
        headers: { "X-PostHog-Task-Run-Id": "run-1" },
      },
      fakeCtx(undefined),
    );
    expect(auth).toEqual({
      baseUrl: "http://127.0.0.1:1234",
      apiKey: "proxy-key",
      headers: { "X-PostHog-Task-Run-Id": "run-1" },
    });
  });

  it("falls back to the posthog provider's resolved api key", async () => {
    const auth = await resolveGatewayAuth(
      { region: "eu" },
      fakeCtx("pha_from_registry"),
    );
    expect(auth).toEqual({
      baseUrl: getLlmGatewayUrl("eu"),
      apiKey: "pha_from_registry",
      headers: {},
    });
  });

  it("throws a descriptive error when no credentials are available", async () => {
    await expect(
      resolveGatewayAuth({ region: "us" }, fakeCtx(undefined)),
    ).rejects.toThrow(/No PostHog gateway credentials/);
  });
});

describe("tryResolveGatewayAuth", () => {
  it("resolves to undefined instead of throwing when no credentials exist", async () => {
    const auth = await tryResolveGatewayAuth(
      { region: "us" },
      fakeCtx(undefined),
    );
    expect(auth).toBeUndefined();
  });

  it("resolves normally when credentials are available", async () => {
    const auth = await tryResolveGatewayAuth(
      { region: "us", apiKey: "pha_static" },
      fakeCtx(undefined),
    );
    expect(auth).toEqual({
      baseUrl: getLlmGatewayUrl("us"),
      apiKey: "pha_static",
      headers: {},
    });
  });
});
