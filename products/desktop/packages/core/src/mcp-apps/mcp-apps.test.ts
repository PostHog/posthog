import { beforeEach, describe, expect, it, vi } from "vitest";
import { McpAppsService } from "./mcp-apps";
import {
  McpAppsServiceEvent,
  type McpResourceUiMeta,
  type McpServerConnectionConfig,
} from "./schemas";

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
const REVIEW_PERMISSIONS = { clipboardWrite: {} };

const UI_META = { ui: { csp: REVIEW_CSP, permissions: REVIEW_PERMISSIONS } };

// metaOn picks whether this client advertises `_meta.ui` on resources/list or
// on the read response.
function makeClient(metaOn: "list" | "read" = "list") {
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
      resources: [
        {
          uri: REVIEW_URI,
          ...(metaOn === "list" ? { _meta: UI_META } : {}),
        } as { uri: string; _meta?: McpResourceUiMeta["_meta"] },
      ],
    })),
    readResource: vi.fn(async ({ uri }: { uri: string }) => ({
      contents: [
        {
          uri,
          mimeType: UI_MIME_TYPE,
          text: "<html></html>",
          ...(metaOn === "read" ? { _meta: UI_META } : {}),
        } as {
          uri: string;
          mimeType: string;
          text: string;
          _meta?: McpResourceUiMeta["_meta"];
        },
      ],
    })),
  };
}

function connectClient(service: McpAppsService, client = makeClient()) {
  vi.spyOn(internals(service), "createConnection").mockImplementation(
    async (c) => ({ name: c.name, client, transport: {} }),
  );
  return client;
}

function connectClients(
  service: McpAppsService,
  clients: Record<string, ReturnType<typeof makeClient>>,
) {
  vi.spyOn(internals(service), "createConnection").mockImplementation(
    async (c) => ({ name: c.name, client: clients[c.name], transport: {} }),
  );
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
    service.setServerConfigs([config("posthog")]);
    vi.spyOn(internals(service), "createConnection").mockRejectedValue(
      new Error("server offline"),
    );
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

  it("treats an unavailable server as having no custom UI", async () => {
    const resolver = vi.fn(async () => {});
    service.setConfigResolver(resolver);

    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).resolves.toBe(false);
    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).resolves.toBe(false);
    expect(resolver).toHaveBeenCalledTimes(1);
  });

  it("discovers an unavailable server after its config is added", async () => {
    const resolver = vi.fn(async () => {});
    service.setConfigResolver(resolver);

    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).resolves.toBe(false);

    service.addServerConfigs([config("posthog")]);
    connectClient(service);
    await expect(
      service.hasUiForTool("mcp__posthog__loops-review"),
    ).resolves.toBe(true);
  });

  it("retries connection failures after the failure backoff expires", async () => {
    vi.useFakeTimers();
    try {
      service.setServerConfigs([config("posthog")]);
      const createConnection = vi
        .spyOn(internals(service), "createConnection")
        .mockRejectedValue(new Error("server offline"));

      await expect(
        service.hasUiForTool("mcp__posthog__loops-review"),
      ).rejects.toThrow("server offline");
      vi.advanceTimersByTime(61_000);
      await expect(
        service.hasUiForTool("mcp__posthog__loops-review"),
      ).rejects.toThrow("server offline");
      expect(createConnection).toHaveBeenCalledTimes(2);
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

  it.each([
    ["the resource listing", "list"],
    ["the read response", "read"],
  ] as const)(
    "attaches UI metadata advertised on %s to direct URI fetches",
    async (_label, metaOn) => {
      service.setConfigResolver(async (name) => {
        service.addServerConfigs([config(name)]);
      });
      connectClient(service, makeClient(metaOn));

      const resource = await service.getUiResourceByUri("posthog", REVIEW_URI);
      expect(resource?.csp).toEqual(REVIEW_CSP);
      expect(resource?.permissions).toEqual(REVIEW_PERMISSIONS);
    },
  );

  it("prefers read-response CSP over the listing CSP", async () => {
    service.setServerConfigs([config("posthog")]);
    const readCsp = { connectDomains: ["https://eu.posthog.com"] };
    const client = makeClient("list");
    client.readResource.mockImplementation(async ({ uri }) => ({
      contents: [
        {
          uri,
          mimeType: UI_MIME_TYPE,
          text: "<html></html>",
          _meta: { ui: { csp: readCsp } },
        },
      ],
    }));
    connectClient(service, client);

    const resource = await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(resource?.csp).toEqual(readCsp);
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

  it("does not cache a CSP-less resource when config appears after warm-up", async () => {
    let resolverCalls = 0;
    service.setConfigResolver(async (name) => {
      resolverCalls += 1;
      if (resolverCalls === 2) {
        service.addServerConfigs([config(name)]);
      }
    });
    const client = makeClient("list");
    connectClient(service, client);

    const first = await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(first?.csp).toBeUndefined();

    const second = await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(second?.csp).toEqual(REVIEW_CSP);
    expect(client.readResource).toHaveBeenCalledTimes(2);

    await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(client.readResource).toHaveBeenCalledTimes(2);
  });

  it("caches a read-advertised resource despite a failed warm-up", async () => {
    service.setServerConfigs([config("posthog")]);
    const client = makeClient("read");
    client.listTools.mockRejectedValue(new Error("listTools broken"));
    connectClient(service, client);

    const first = await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(first?.csp).toEqual(REVIEW_CSP);
    await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(client.readResource).toHaveBeenCalledTimes(1);
  });

  it("caches same-URI resources separately per server", async () => {
    service.setServerConfigs([config("posthog"), config("staging")]);
    const stagingClient = makeClient();
    stagingClient.readResource.mockImplementation(async ({ uri }) => ({
      contents: [{ uri, mimeType: UI_MIME_TYPE, text: "<html>staging</html>" }],
    }));
    connectClients(service, { posthog: makeClient(), staging: stagingClient });

    const posthogResource = await service.getUiResourceByUri(
      "posthog",
      REVIEW_URI,
    );
    const stagingResource = await service.getUiResourceByUri(
      "staging",
      REVIEW_URI,
    );

    expect(posthogResource?.html).toBe("<html></html>");
    expect(stagingResource?.html).toBe("<html>staging</html>");
  });

  it("evicts only the disconnected server's cached resources", async () => {
    service.setServerConfigs([config("posthog"), config("staging")]);
    const posthogClient = makeClient();
    const stagingClient = makeClient();
    connectClients(service, { posthog: posthogClient, staging: stagingClient });

    await service.getUiResourceByUri("posthog", REVIEW_URI);
    await service.getUiResourceByUri("staging", REVIEW_URI);
    await service.disconnectServer("posthog");

    await service.getUiResourceByUri("staging", REVIEW_URI);
    expect(stagingClient.readResource).toHaveBeenCalledTimes(1);
    await service.getUiResourceByUri("posthog", REVIEW_URI);
    expect(posthogClient.readResource).toHaveBeenCalledTimes(2);
  });
});
