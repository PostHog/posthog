import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { McpServerInstallation } from "@posthog/api-client/types";
import type { LocalMcpServerDescriptor } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  addMcpServer,
  localMcpServers,
  type McpClient,
  mcpSheet,
  reauthorizeMcpServer,
  relayedMcpServers,
} from "./mcp";

const installation = (
  fields: Partial<McpServerInstallation>,
): McpServerInstallation =>
  ({
    id: "i1",
    name: "linear",
    display_name: "Linear",
    tool_count: 12,
    needs_reauth: false,
    pending_oauth: false,
    is_enabled: true,
    ...fields,
  }) as McpServerInstallation;

const stdio = (name: string): LocalMcpServerDescriptor => ({
  name,
  scope: "user",
  transport: { type: "stdio", command: "npx", args: [`@${name}/mcp`] },
});
const http = (name: string, url: string): LocalMcpServerDescriptor => ({
  name,
  scope: "project",
  transport: { type: "http", url },
});

describe("mcpSheet", () => {
  it("lists the account's servers with their state, then this machine's, in name order, then add and the relay switch", () => {
    const sheet = mcpSheet(
      [
        installation({
          id: "i2",
          name: "zapier",
          display_name: "Zapier",
          needs_reauth: true,
        }),
        installation({}),
        installation({
          id: "i3",
          name: "custom",
          display_name: "",
          pending_oauth: true,
        }),
        installation({
          id: "i4",
          name: "old",
          display_name: "Old",
          is_enabled: false,
        }),
      ],
      [stdio("playwright"), http("intranet", "http://10.0.0.2/mcp")],
    );

    expect(sheet.items.map((item) => [item.label, item.detail])).toEqual([
      ["custom", "PostHog · finishing sign-in"],
      ["Linear", "PostHog · 12 tools"],
      ["Old", "PostHog · off"],
      ["Zapier", "PostHog · needs signing in again · Enter to sign in"],
      ["intranet", "this machine · http://10.0.0.2/mcp"],
      ["playwright", "this machine · npx @playwright/mcp"],
      ["Add a server", "a URL, and how it signs you in"],
      ["Cloud chats reach this machine's servers", undefined],
    ]);
    expect(sheet.items.at(-1)?.current).toBe(false);
    expect(sheet.addServer).toBe(6);
    expect(sheet.relayToggle).toBe(7);
    // Enter on a server that lost its sign-in runs it again.
    expect([...sheet.reauth.keys()]).toEqual([3]);
    expect(sheet.reauth.get(3)?.id).toBe("i2");
  });

  it("marks the servers cloud chats reach through this machine once the relay is on", () => {
    const sheet = mcpSheet(
      [],
      [stdio("playwright"), http("public", "https://mcp.example.com")],
      { relay: true },
    );
    expect(
      sheet.items.map((item) => [item.label, item.detail, item.current]),
    ).toEqual([
      [
        "playwright",
        "this machine · npx @playwright/mcp · relayed to cloud chats",
        undefined,
      ],
      ["public", "this machine · https://mcp.example.com", undefined],
      ["Add a server", "a URL, and how it signs you in", undefined],
      ["Cloud chats reach this machine's servers", undefined, true],
    ]);
  });

  it("still offers to add a server when there are none", () => {
    expect(mcpSheet([], []).items.map((item) => item.label)).toEqual([
      "Add a server",
      "Cloud chats reach this machine's servers",
    ]);
  });
});

describe("addMcpServer and reauthorizeMcpServer", () => {
  const client = (
    installed: McpServerInstallation,
    pending: McpServerInstallation[][],
  ): McpClient & { install: ReturnType<typeof vi.fn> } => ({
    installations: vi.fn(async () => pending.shift() ?? [installed]),
    install: vi.fn(async () =>
      installed.auth_type === "oauth"
        ? { redirect_url: "https://auth.example.com/start" }
        : installed,
    ),
    authorize: vi.fn(async () => ({
      redirect_url: "https://auth.example.com/again",
    })),
  });

  it("installs a server on an API key straight away, sending the key only when there is one", async () => {
    const installed = installation({ auth_type: "api_key" });
    const api = client(installed, []);
    const open = vi.fn();

    await expect(
      addMcpServer(
        api,
        { name: "Linear", url: "https://mcp.example.com", auth: "none" },
        open,
      ),
    ).resolves.toBe(installed);

    expect(api.install).toHaveBeenCalledWith({
      name: "Linear",
      url: "https://mcp.example.com",
      auth_type: "api_key",
      install_source: "posthog-code",
    });
    expect(open).not.toHaveBeenCalled();
  });

  it("opens the browser for an OAuth server and waits until PostHog says the sign-in finished", async () => {
    const done = installation({ auth_type: "oauth" });
    const api = client(done, [
      [installation({ auth_type: "oauth", pending_oauth: true })],
    ]);
    const open = vi.fn();

    const added = await addMcpServer(
      api,
      { name: "Linear", url: "https://mcp.example.com", auth: "oauth" },
      open,
      { every: 0, timeout: 1000 },
    );

    expect(open).toHaveBeenCalledWith("https://auth.example.com/start");
    expect(added).toBe(done);
    expect(api.installations).toHaveBeenCalledTimes(2);
  });

  it("gives up when the sign-in never finishes", async () => {
    const api = client(
      installation({ auth_type: "oauth", pending_oauth: true }),
      [],
    );

    await expect(
      addMcpServer(
        api,
        { name: "Linear", url: "https://mcp.example.com", auth: "oauth" },
        () => {},
        { every: 0, timeout: 0 },
      ),
    ).rejects.toThrow("The sign-in did not finish in time");
  });

  it("signs a server in again from its authorize link and waits for the sign-in", async () => {
    const stale = installation({ needs_reauth: true });
    const api = client(installation({}), [[stale]]);
    const open = vi.fn();

    await expect(
      reauthorizeMcpServer(api, stale, open, { every: 0, timeout: 1000 }),
    ).resolves.toMatchObject({ id: "i1", needs_reauth: false });
    expect(open).toHaveBeenCalledWith("https://auth.example.com/again");
  });
});

describe("relayedMcpServers", () => {
  it("names only the servers a sandbox cannot reach on its own", () => {
    expect(
      relayedMcpServers([
        stdio("playwright"),
        http("intranet", "http://10.0.0.2/mcp"),
        http("public", "https://mcp.example.com"),
        http("posthog", "http://localhost:8000/mcp"),
      ]),
    ).toEqual(["intranet", "playwright"]);
  });
});

describe("localMcpServers", () => {
  it("reads the user's servers and the folder's own from ~/.claude.json", () => {
    const home = mkdtempSync(join(tmpdir(), "tui-mcp-"));
    writeFileSync(
      join(home, ".claude.json"),
      JSON.stringify({
        mcpServers: {
          playwright: { command: "npx", args: ["@playwright/mcp"] },
        },
        projects: {
          "/work/app": {
            mcpServers: {
              intranet: { type: "http", url: "http://10.0.0.2/mcp" },
            },
          },
        },
      }),
    );
    expect(
      localMcpServers("/work/app", home)
        .map((server) => server.name)
        .sort(),
    ).toEqual(["intranet", "playwright"]);
    expect(
      localMcpServers("/elsewhere", home).map((server) => server.name),
    ).toEqual(["playwright"]);
  });
});
