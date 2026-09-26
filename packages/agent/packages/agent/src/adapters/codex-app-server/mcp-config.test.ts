import type { McpServer } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { codexKeyMatchesMcpServerName, toCodexMcpServers } from "./mcp-config";

describe("toCodexMcpServers", () => {
  it("returns undefined for empty input", () => {
    expect(toCodexMcpServers(undefined)).toBeUndefined();
    expect(toCodexMcpServers([])).toBeUndefined();
  });

  it("translates a stdio server, folding env pairs into a map", () => {
    const servers = [
      {
        name: "posthog",
        command: "node",
        args: ["server.js"],
        env: [
          { name: "TOKEN", value: "abc" },
          { name: "BASE", value: "http://x" },
        ],
      },
    ] as unknown as McpServer[];

    expect(toCodexMcpServers(servers)).toEqual({
      posthog: {
        command: "node",
        args: ["server.js"],
        env: { TOKEN: "abc", BASE: "http://x" },
      },
    });
  });

  it("omits env when there are no pairs", () => {
    const servers = [
      { name: "bare", command: "run", args: [], env: [] },
    ] as unknown as McpServer[];

    expect(toCodexMcpServers(servers)).toEqual({
      bare: { command: "run", args: [] },
    });
  });

  it("translates an http server, folding headers into http_headers", () => {
    const servers = [
      {
        type: "http",
        name: "remote",
        url: "https://mcp.example/mcp",
        headers: [{ name: "Authorization", value: "Bearer t" }],
      },
    ] as unknown as McpServer[];

    expect(toCodexMcpServers(servers)).toEqual({
      remote: {
        url: "https://mcp.example/mcp",
        http_headers: { Authorization: "Bearer t" },
      },
    });
  });

  it("prompts for PostHog exec when gating is enabled", () => {
    const servers = [
      {
        type: "http",
        name: "posthog_cloud",
        url: "https://mcp.example/mcp",
      },
      {
        type: "http",
        name: "other",
        url: "https://other.example/mcp",
      },
    ] as unknown as McpServer[];

    expect(toCodexMcpServers(servers, { gatePosthogExec: true })).toEqual({
      posthog_cloud: {
        url: "https://mcp.example/mcp",
        tools: { exec: { approval_mode: "prompt" } },
      },
      other: { url: "https://other.example/mcp" },
    });
  });

  // Codex rejects server names outside ^[a-zA-Z0-9_-]+$ and silently never
  // starts the server, so MCP Store display names must be sanitized here.
  it.each([
    ["Google Calendar", "Google_Calendar"],
    ["Linear (Jane Doe)", "Linear__Jane_Doe_"],
  ])("sanitizes %j into a codex-valid server key", (name, expected) => {
    const servers = [
      { type: "http", name, url: "https://mcp.example/mcp" },
    ] as unknown as McpServer[];

    expect(toCodexMcpServers(servers)).toEqual({
      [expected]: { url: "https://mcp.example/mcp" },
    });
  });

  it("suffixes colliding sanitized names instead of dropping a server", () => {
    const servers = [
      { type: "http", name: "Notion (A)", url: "https://a.example/mcp" },
      { type: "http", name: "Notion [A]", url: "https://b.example/mcp" },
    ] as unknown as McpServer[];

    expect(toCodexMcpServers(servers)).toEqual({
      Notion__A_: { url: "https://a.example/mcp" },
      Notion__A__2: { url: "https://b.example/mcp" },
    });
  });

  // Consumers match codex-reported keys against raw names without seeing the
  // assignment order, so the matcher must cover the suffixed collision form;
  // missing it lets a relayed tool bypass its always-ask gate.
  it.each([
    ["My Slack", "My Slack", true],
    ["My_Slack", "My Slack", true],
    ["My_Slack_2", "My Slack", true],
    ["My_Slack_10", "My Slack", true],
    ["My_Slack2", "My Slack", false],
    ["My_Slack_x", "My Slack", false],
    ["My_Slack_", "My Slack", false],
    ["Other_Server", "My Slack", false],
  ])("codexKeyMatchesMcpServerName(%j, %j) is %s", (key, name, expected) => {
    expect(codexKeyMatchesMcpServerName(key, name)).toBe(expected);
  });

  it("leaves PostHog exec unchanged when gating is not enabled", () => {
    const servers = [
      {
        type: "http",
        name: "posthog",
        url: "https://mcp.example/mcp",
      },
    ] as unknown as McpServer[];

    expect(toCodexMcpServers(servers)).toEqual({
      posthog: { url: "https://mcp.example/mcp" },
    });
  });
});
