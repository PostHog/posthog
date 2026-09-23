import { describe, expect, it } from "vitest";
import { createBrowserMcpServer } from "./browser-mcp";

describe("createBrowserMcpServer", () => {
  it("uses an unambiguous name and redacts network headers", () => {
    const server = createBrowserMcpServer();

    expect(server.name).toBe("chrome-devtools");
    expect(server.args).toContain("--redact-network-headers");
  });
});
