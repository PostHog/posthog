import type { LocalMcpServerDescriptor } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  classifyLocalMcpServer,
  isPrivateHostname,
  type LocalMcpCloudClassification,
  LocalMcpImportService,
  type LocalMcpWorkspaceClient,
  partitionLocalMcpServersForRun,
} from "./localMcpImport";

describe("isPrivateHostname", () => {
  it.each([
    // loopback and localhost
    { hostname: "localhost", isPrivate: true },
    { hostname: "LOCALHOST", isPrivate: true },
    { hostname: "app.localhost", isPrivate: true },
    { hostname: "127.0.0.1", isPrivate: true },
    { hostname: "127.9.9.9", isPrivate: true },
    { hostname: "0.0.0.0", isPrivate: true },
    { hostname: "::1", isPrivate: true },
    { hostname: "[::1]", isPrivate: true },
    // RFC1918 / link-local / CGNAT
    { hostname: "10.0.0.5", isPrivate: true },
    { hostname: "172.16.0.1", isPrivate: true },
    { hostname: "172.31.255.255", isPrivate: true },
    { hostname: "192.168.1.10", isPrivate: true },
    { hostname: "169.254.1.1", isPrivate: true },
    { hostname: "100.64.0.1", isPrivate: true },
    { hostname: "100.101.102.103", isPrivate: true },
    // IPv6 private ranges
    { hostname: "fd12:3456:789a::1", isPrivate: true },
    { hostname: "fc00::1", isPrivate: true },
    { hostname: "fe80::1", isPrivate: true },
    { hostname: "::ffff:192.168.0.1", isPrivate: true },
    // private-looking names
    { hostname: "nas", isPrivate: true },
    { hostname: "grafana.local", isPrivate: true },
    { hostname: "vault.internal", isPrivate: true },
    { hostname: "printer.lan", isPrivate: true },
    { hostname: "server.home.arpa", isPrivate: true },
    { hostname: "router.home", isPrivate: true },
    { hostname: "machine.tailnet-1234.ts.net", isPrivate: true },
    { hostname: "example.com.", isPrivate: false },
    // public
    { hostname: "mcp.example.com", isPrivate: false },
    { hostname: "8.8.8.8", isPrivate: false },
    { hostname: "172.32.0.1", isPrivate: false },
    { hostname: "100.128.0.1", isPrivate: false },
    { hostname: "2606:4700::6810:84e5", isPrivate: false },
    { hostname: "::ffff:8.8.8.8", isPrivate: false },
    { hostname: "internal.example.com", isPrivate: false },
    { hostname: "localhost.example.com", isPrivate: false },
  ])("$hostname -> $isPrivate", ({ hostname, isPrivate }) => {
    expect(isPrivateHostname(hostname)).toBe(isPrivate);
  });
});

function server(
  transport: LocalMcpServerDescriptor["transport"],
  overrides?: Partial<LocalMcpServerDescriptor>,
): LocalMcpServerDescriptor {
  return { name: "server", scope: "user", ...overrides, transport };
}

interface ClassifyCase {
  name: string;
  transport: LocalMcpServerDescriptor["transport"];
  availability: "importable" | "requires_desktop" | "unsupported";
  reason: string;
}

describe("classifyLocalMcpServer", () => {
  it("marks a public http server importable with sandbox-shaped config", () => {
    const result = classifyLocalMcpServer(
      server(
        {
          type: "http",
          url: "https://mcp.grafana.example.com/mcp",
          headers: { Authorization: "Bearer abc" },
        },
        { name: "grafana", scope: "project" },
      ),
    );
    expect(result).toEqual({
      name: "grafana",
      availability: "importable",
      reason: "public_url",
      remote: {
        type: "http",
        name: "grafana",
        url: "https://mcp.grafana.example.com/mcp",
        headers: [{ name: "Authorization", value: "Bearer abc" }],
      },
    });
  });

  it.each(["posthog", "PostHog"])(
    "marks a server named %s built-in instead of importing it",
    (name) => {
      const result = classifyLocalMcpServer(
        server({ type: "http", url: "https://mcp.posthog.com/mcp" }, { name }),
      );
      expect(result).toEqual({
        name,
        availability: "built_in",
        reason: "reserved_name",
      });
    },
  );

  it.each<ClassifyCase>([
    {
      name: "sse server on a public host",
      transport: { type: "sse", url: "https://sse.example.com/mcp" },
      availability: "importable",
      reason: "public_url",
    },
    {
      name: "http server on localhost",
      transport: { type: "http", url: "http://localhost:3001/mcp" },
      availability: "requires_desktop",
      reason: "private_url",
    },
    {
      name: "http server on an RFC1918 address",
      transport: { type: "http", url: "http://192.168.1.4:8000/mcp" },
      availability: "requires_desktop",
      reason: "private_url",
    },
    {
      name: "http server on a tailnet host",
      transport: {
        type: "http",
        url: "https://grafana.tailnet-abcd.ts.net/mcp",
      },
      availability: "requires_desktop",
      reason: "private_url",
    },
    {
      name: "stdio server",
      transport: { type: "stdio", command: "npx", args: ["some-mcp"] },
      availability: "requires_desktop",
      reason: "stdio_transport",
    },
    {
      name: "server with an unparseable url",
      transport: { type: "http", url: "not a url" },
      availability: "unsupported",
      reason: "invalid_url",
    },
    {
      name: "server with a non-http scheme",
      transport: { type: "http", url: "ftp://example.com/mcp" },
      availability: "unsupported",
      reason: "invalid_url",
    },
    {
      name: "server with an unrecognized transport",
      transport: { type: "unknown" },
      availability: "unsupported",
      reason: "unsupported_transport",
    },
  ])("$name -> $availability", ({ transport, availability, reason }) => {
    const result = classifyLocalMcpServer(server(transport));
    expect(result.availability).toBe(availability);
    expect(result.reason).toBe(reason);
    if (availability === "importable") {
      expect(result.remote).toBeDefined();
    } else {
      expect(result.remote).toBeUndefined();
    }
  });
});

describe("LocalMcpImportService", () => {
  it("classifies everything the workspace client reports, passing cwd through", async () => {
    const listed: Array<string | undefined> = [];
    const workspace: LocalMcpWorkspaceClient = {
      listLocalMcpServers: async (cwd) => {
        listed.push(cwd);
        return [
          server({ type: "http", url: "https://mcp.example.com" }),
          server({ type: "stdio", command: "npx" }, { name: "local" }),
        ];
      },
    };

    const results = await new LocalMcpImportService(
      workspace,
    ).getCloudAvailability("/repo");

    expect(listed).toEqual(["/repo"]);
    expect(results.map((r) => [r.name, r.availability])).toEqual([
      ["server", "importable"],
      ["local", "requires_desktop"],
    ]);
  });
});

describe("partitionLocalMcpServersForRun", () => {
  const importable = (name: string): LocalMcpCloudClassification => ({
    name,
    availability: "importable",
    reason: "public_url",
    remote: {
      type: "http",
      name,
      url: `https://${name}.example.com/mcp`,
      headers: [],
    },
  });
  const desktopOnly = (name: string): LocalMcpCloudClassification => ({
    name,
    availability: "requires_desktop",
    reason: "stdio_transport",
  });
  const servers = [
    importable("grafana"),
    desktopOnly("slack"),
    { name: "posthog", availability: "built_in", reason: "reserved_name" },
    { name: "broken", availability: "unsupported", reason: "invalid_url" },
  ] as LocalMcpCloudClassification[];

  it.each([
    ["claude", "claude"],
    ["unset", undefined],
  ] as const)("imports public servers for the %s adapter", (_name, adapter) => {
    const result = partitionLocalMcpServersForRun(servers, adapter);
    expect(result.imported.map((s) => s.name)).toEqual(["grafana"]);
    expect(result.relayed).toEqual([{ name: "slack" }]);
  });

  it("relays importable servers instead of importing them for codex", () => {
    const result = partitionLocalMcpServersForRun(servers, "codex");
    expect(result.imported).toEqual([]);
    expect(result.relayed).toEqual([{ name: "slack" }, { name: "grafana" }]);
  });

  it("keeps desktop-only servers when the codex relay list hits the cap", () => {
    const many = [
      ...Array.from({ length: 15 }, (_, i) => importable(`pub-${i}`)),
      ...Array.from({ length: 10 }, (_, i) => desktopOnly(`desk-${i}`)),
    ];
    const result = partitionLocalMcpServersForRun(many, "codex");
    expect(result.relayed).toHaveLength(20);
    const names = result.relayed.map((s) => s.name);
    for (let i = 0; i < 10; i++) expect(names).toContain(`desk-${i}`);
  });
});
