import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { McpServerInstallation } from "@posthog/api-client/types";
import { describe, expect, it } from "vitest";
import { localMcpServers, mcpSheet } from "./mcp";

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

describe("mcpSheet", () => {
  it("lists the account's servers with their state, then this machine's, in name order", () => {
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
      [
        {
          name: "playwright",
          scope: "user",
          transport: {
            type: "stdio",
            command: "npx",
            args: ["@playwright/mcp"],
          },
        },
        {
          name: "intranet",
          scope: "project",
          transport: { type: "http", url: "http://10.0.0.2/mcp" },
        },
      ],
    );

    expect(sheet.items.map((item) => [item.label, item.detail])).toEqual([
      ["custom", "PostHog · finishing sign-in"],
      ["Linear", "PostHog · 12 tools"],
      ["Old", "PostHog · off"],
      ["Zapier", "PostHog · needs signing in again"],
      ["intranet", "this machine · http://10.0.0.2/mcp"],
      ["playwright", "this machine · npx @playwright/mcp"],
    ]);
  });

  it("says so when there are no servers, so the sheet still draws", () => {
    const sheet = mcpSheet([], []);
    expect(sheet.items).toEqual([
      {
        label: "No MCP servers yet",
        disabled: "add one in PostHog's MCP settings",
      },
    ]);
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
