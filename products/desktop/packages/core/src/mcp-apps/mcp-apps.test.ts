import { beforeEach, describe, expect, it, vi } from "vitest";
import { McpAppsService } from "./mcp-apps";
import type { McpServerConnectionConfig } from "./schemas";

function makeLogger() {
  const scopedLog = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  return { ...scopedLog, scope: vi.fn(() => scopedLog) };
}

function makeService(): McpAppsService {
  const urlLauncher = { launch: vi.fn() };
  return new McpAppsService(urlLauncher as never, makeLogger() as never);
}

describe("McpAppsService.getUiResourceByUri", () => {
  let service: McpAppsService;

  beforeEach(() => {
    service = makeService();
  });

  it("rejects non-ui:// URIs without attempting a fetch", async () => {
    await expect(
      service.getUiResourceByUri("posthog", "https://evil.example/app.html"),
    ).resolves.toBeNull();
    await expect(
      service.getUiResourceByUri("posthog", "file:///etc/passwd"),
    ).resolves.toBeNull();
  });

  it("rejects when the server has no connection config", async () => {
    await expect(
      service.getUiResourceByUri("posthog", "ui://posthog/survey-list.html"),
    ).rejects.toThrow("No server config for: posthog");
  });
});

type ConnectionInternals = {
  getOrCreateConnection(serverName: string): Promise<unknown>;
  createConnection(config: McpServerConnectionConfig): Promise<unknown>;
};

function internals(service: McpAppsService): ConnectionInternals {
  return service as unknown as ConnectionInternals;
}

function config(name: string): McpServerConnectionConfig {
  return { name, url: `https://example.test/${name}/mcp`, headers: {} };
}

describe("McpAppsService config resolver", () => {
  let service: McpAppsService;

  beforeEach(() => {
    service = makeService();
  });

  it("connects after the resolver supplies the missing config", async () => {
    service.setConfigResolver(async (name) => {
      service.addServerConfigs([config(name)]);
    });
    const createConnection = vi
      .spyOn(internals(service), "createConnection")
      .mockImplementation(async (c) => ({ name: c.name }));

    await expect(
      internals(service).getOrCreateConnection("posthog"),
    ).resolves.toEqual({ name: "posthog" });
    expect(createConnection).toHaveBeenCalledWith(config("posthog"));
  });

  it("still throws when the resolver leaves the config missing", async () => {
    const resolver = vi.fn(async () => {});
    service.setConfigResolver(resolver);

    await expect(
      internals(service).getOrCreateConnection("posthog"),
    ).rejects.toThrow("No server config for: posthog");
    expect(resolver).toHaveBeenCalledWith("posthog");
  });

  it("dedupes concurrent callers waiting on the resolver", async () => {
    const resolver = vi.fn(async (name: string) => {
      await new Promise((resolve) => setTimeout(resolve, 5));
      service.addServerConfigs([config(name)]);
    });
    service.setConfigResolver(resolver);
    const createConnection = vi
      .spyOn(internals(service), "createConnection")
      .mockImplementation(async (c) => ({ name: c.name }));

    const [first, second] = await Promise.all([
      internals(service).getOrCreateConnection("posthog"),
      internals(service).getOrCreateConnection("posthog"),
    ]);

    expect(first).toBe(second);
    expect(resolver).toHaveBeenCalledTimes(1);
    expect(createConnection).toHaveBeenCalledTimes(1);
  });

  it("addServerConfigs merges without clearing existing configs", async () => {
    service.setServerConfigs([config("posthog")]);
    service.addServerConfigs([config("installation")]);
    const createConnection = vi
      .spyOn(internals(service), "createConnection")
      .mockImplementation(async (c) => ({ name: c.name }));

    await internals(service).getOrCreateConnection("posthog");
    await internals(service).getOrCreateConnection("installation");
    expect(createConnection).toHaveBeenCalledTimes(2);
  });
});
