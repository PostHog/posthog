import { beforeEach, describe, expect, it, vi } from "vitest";
import { McpAppsService } from "./mcp-apps";
import { McpAppsServiceEvent, type McpServerConnectionConfig } from "./schemas";

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

const UI_MIME_TYPE = "text/html;profile=mcp-app";
const REVIEW_URI = "ui://posthog/loops-review.html";
const REVIEW_CSP = { connectDomains: ["https://us.posthog.com"] };

function makeClient() {
  return {
    close: vi.fn(async () => {}),
    listTools: vi.fn(async () => ({
      tools: [
        {
          name: "loops-review",
          _meta: { ui: { resourceUri: REVIEW_URI } },
        },
        { name: "loops-list" },
      ],
    })),
    listResources: vi.fn(async () => ({
      resources: [{ uri: REVIEW_URI, _meta: { ui: { csp: REVIEW_CSP } } }],
    })),
    readResource: vi.fn(async ({ uri }: { uri: string }) => ({
      contents: [{ uri, mimeType: UI_MIME_TYPE, text: "<html></html>" }],
    })),
  };
}

function connectClient(service: McpAppsService, client = makeClient()) {
  vi.spyOn(internals(service), "createConnection").mockImplementation(
    async (c) => ({ name: c.name, client, transport: {} }),
  );
  return client;
}

describe("McpAppsService lazy discovery", () => {
  let service: McpAppsService;

  beforeEach(() => {
    service = makeService();
  });

  it("discovers on first hasUiForTool when no session ran discovery", async () => {
    service.setConfigResolver(async (name) => {
      service.addServerConfigs([config(name)]);
    });
    const client = connectClient(service);

    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).resolves.toBe(true);
    expect(client.listTools).toHaveBeenCalledTimes(1);
  });

  it("emits DiscoveryComplete after a lazy discovery", async () => {
    service.setServerConfigs([config("posthog")]);
    connectClient(service);
    const onComplete = vi.fn();
    service.on(McpAppsServiceEvent.DiscoveryComplete, onComplete);

    await service.hasUiForTool("mcp__posthog__loops-review");

    expect(onComplete).toHaveBeenCalledExactlyOnceWith({
      toolKeys: ["mcp__posthog__loops-review"],
    });
  });

  it("dedupes concurrent lazy discoveries and emits once", async () => {
    service.setServerConfigs([config("posthog")]);
    const client = connectClient(service);
    const onComplete = vi.fn();
    service.on(McpAppsServiceEvent.DiscoveryComplete, onComplete);

    const [reviewHasUi, listHasUi] = await Promise.all([
      service.hasUiForTool("mcp__posthog__loops-review"),
      service.hasUiForTool("mcp__posthog__loops-list"),
    ]);

    expect(reviewHasUi).toBe(true);
    expect(listHasUi).toBe(false);
    expect(client.listTools).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("does not emit DiscoveryComplete when lazy discovery fails", async () => {
    service.setConfigResolver(vi.fn(async () => {}));
    const onComplete = vi.fn();
    service.on(McpAppsServiceEvent.DiscoveryComplete, onComplete);

    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).rejects.toThrow();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it.each([
    ["a non-MCP tool", "Bash"],
    ["a malformed MCP key", "mcp__posthog"],
  ])("returns false for %s without connecting", async (_label, toolKey) => {
    const createConnection = vi.spyOn(internals(service), "createConnection");

    await expect(service.hasUiForTool(toolKey)).resolves.toBe(false);
    expect(createConnection).not.toHaveBeenCalled();
  });

  it.each([
    ["a non-MCP tool", "Bash"],
    ["a malformed MCP key", "mcp__posthog"],
  ])(
    "getUiResourceForTool returns null for %s without connecting",
    async (_label, toolKey) => {
      const createConnection = vi.spyOn(internals(service), "createConnection");

      await expect(service.getUiResourceForTool(toolKey)).resolves.toBeNull();
      expect(createConnection).not.toHaveBeenCalled();
    },
  );

  it("answers UI-less tools from the discovered cache without re-listing", async () => {
    service.setServerConfigs([config("posthog")]);
    const client = connectClient(service);

    await service.hasUiForTool("mcp__posthog__loops-review");
    await expect(
      service.hasUiForTool("mcp__posthog__loops-list"),
    ).resolves.toBe(false);
    expect(client.listTools).toHaveBeenCalledTimes(1);
  });

  it("rethrows discovery failures and backs off retries", async () => {
    const resolver = vi.fn(async () => {});
    service.setConfigResolver(resolver);

    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).rejects.toThrow("No server config for: posthog");
    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).rejects.toThrow("UI tool discovery recently failed for: posthog");
    expect(resolver).toHaveBeenCalledTimes(1);
  });

  it("retries discovery after the failure backoff expires", async () => {
    vi.useFakeTimers();
    try {
      const resolver = vi.fn(async () => {});
      service.setConfigResolver(resolver);

      await expect(
        service.hasUiForTool("mcp__posthog__loops-review"),
      ).rejects.toThrow("No server config for: posthog");
      vi.advanceTimersByTime(61_000);
      await expect(
        service.hasUiForTool("mcp__posthog__loops-review"),
      ).rejects.toThrow("No server config for: posthog");
      expect(resolver).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("skips re-listing when handleDiscovery already discovered the server", async () => {
    service.setServerConfigs([config("posthog")]);
    const client = connectClient(service);

    await service.handleDiscovery(["posthog"]);
    await expect(
      service.hasUiForTool("mcp__posthog__loops-list"),
    ).resolves.toBe(false);
    expect(client.listTools).toHaveBeenCalledTimes(1);
  });

  it("re-lists on handleDiscovery even when already discovered", async () => {
    service.setServerConfigs([config("posthog")]);
    const client = connectClient(service);

    await service.hasUiForTool("mcp__posthog__loops-review");
    await service.handleDiscovery(["posthog"]);
    expect(client.listTools).toHaveBeenCalledTimes(2);
  });

  it("re-discovers after disconnectServer clears server state", async () => {
    service.setServerConfigs([config("posthog")]);
    const client = connectClient(service);

    await service.hasUiForTool("mcp__posthog__loops-review");
    await service.disconnectServer("posthog");
    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).resolves.toBe(true);
    expect(client.listTools).toHaveBeenCalledTimes(2);
  });

  it("resolves lazily-discovered UI resources for a tool", async () => {
    service.setServerConfigs([config("posthog")]);
    connectClient(service);

    const resource = await service.getUiResourceForTool(
      "mcp__posthog__loops-review",
    );
    expect(resource?.uri).toBe(REVIEW_URI);
    expect(resource?.html).toBe("<html></html>");
  });

  it("attaches discovered CSP metadata on direct URI fetches", async () => {
    service.setConfigResolver(async (name) => {
      service.addServerConfigs([config(name)]);
    });
    connectClient(service);

    const resource = await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(resource?.csp).toEqual(REVIEW_CSP);
  });

  it("returns an uncached resource when the metadata warm-up fails", async () => {
    service.setServerConfigs([config("posthog")]);
    const client = makeClient();
    client.listTools.mockRejectedValue(new Error("listTools broken"));
    connectClient(service, client);

    const first = await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(first?.html).toBe("<html></html>");
    expect(first?.csp).toBeUndefined();

    const second = await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(second?.html).toBe("<html></html>");
    expect(client.readResource).toHaveBeenCalledTimes(2);
  });
});
