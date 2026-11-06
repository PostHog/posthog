import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import posthogProvider, { createPosthogProviderExtension } from "./extension";
import { getLlmGatewayUrl } from "./gateway";
import { POSTHOG_PROVIDER_NAME } from "./provider";

function fakeApi(): ExtensionAPI {
  return {
    registerProvider: vi.fn(),
  } as unknown as ExtensionAPI;
}

describe("createPosthogProviderExtension", () => {
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

  it("registers the posthog provider with a resolved config", async () => {
    const pi = fakeApi();
    const factory = createPosthogProviderExtension({ region: "us" });

    await factory(pi);

    expect(pi.registerProvider).toHaveBeenCalledTimes(1);
    const [name, config] = (pi.registerProvider as ReturnType<typeof vi.fn>)
      .mock.calls[0];
    expect(name).toBe(POSTHOG_PROVIDER_NAME);
    expect(config.baseUrl).toBe(getLlmGatewayUrl("us"));
    expect(config.models?.length).toBeGreaterThan(0);
  });

  it("forwards a static api key option through to the registered config", async () => {
    const pi = fakeApi();
    const factory = createPosthogProviderExtension({ apiKey: "pha_test" });

    await factory(pi);

    const [, config] = (pi.registerProvider as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(config.apiKey).toBe("pha_test");
  });
});

describe("posthogProvider default export", () => {
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

  it("registers the posthog provider using default options", async () => {
    const pi = fakeApi();

    await posthogProvider(pi);

    expect(pi.registerProvider).toHaveBeenCalledTimes(1);
    const [name] = (pi.registerProvider as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(name).toBe(POSTHOG_PROVIDER_NAME);
  });
});
