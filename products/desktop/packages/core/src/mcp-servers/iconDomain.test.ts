import { describe, expect, it } from "vitest";
import { iconDomainFromServerUrl } from "./iconDomain";

describe("iconDomainFromServerUrl", () => {
  it.each([
    ["strips mcp. from deep hosts", "https://mcp.linear.app/sse", "linear.app"],
    ["strips api. from deep hosts", "https://api.acme.com/mcp", "acme.com"],
    ["strips www. from deep hosts", "https://www.acme.com/mcp", "acme.com"],
    ["keeps bare brand domains", "https://notion.com/mcp", "notion.com"],
    [
      "keeps two-label hosts named like a prefix",
      "https://mcp.com/x",
      "mcp.com",
    ],
    [
      "keeps unrelated subdomains",
      "https://server.smithery.ai/mcp",
      "server.smithery.ai",
    ],
    ["lowercases the host", "https://MCP.Linear.APP/sse", "linear.app"],
  ])("%s", (_name, url, expected) => {
    expect(iconDomainFromServerUrl(url)).toBe(expected);
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["an empty string", ""],
    ["a non-URL", "not a url"],
    ["a dotless host", "https://localhost:3000/mcp"],
  ])("returns null for %s", (_name, url) => {
    expect(iconDomainFromServerUrl(url)).toBeNull();
  });
});
