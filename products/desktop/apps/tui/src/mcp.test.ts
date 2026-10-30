import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { McpServerInstallation } from "@posthog/api-client/types";
import type { LocalMcpServerDescriptor } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { localMcpServers, mcpSheet, relayedMcpServers } from "./mcp";

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
  it("lists the account's servers with their state, then this machine's, in name order, then the relay switch", () => {
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
      ["Zapier", "PostHog · needs signing in again"],
      ["intranet", "this machine · http://10.0.0.2/mcp"],
      ["playwright", "this machine · npx @playwright/mcp"],
      ["Cloud chats reach this machine's servers", undefined],
    ]);
    expect(sheet.items.at(-1)?.current).toBe(false);
    expect(sheet.relayToggle).toBe(6);
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
      ["Cloud chats reach this machine's servers", undefined, true],
    ]);
  });

  it("says so when there are no servers, so the sheet still draws", () => {
    expect(mcpSheet([], []).items.map((item) => item.label)).toEqual([
      "No MCP servers yet",
      "Cloud chats reach this machine's servers",
    ]);
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
