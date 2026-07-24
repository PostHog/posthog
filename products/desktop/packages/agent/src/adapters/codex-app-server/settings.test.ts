import { describe, expect, it, vi } from "vitest";

const readFileSync = vi.hoisted(() => vi.fn());
vi.mock("node:fs", () => ({ readFileSync }));

const { CodexSettingsManager } = await import("./settings");

function serverNamesFor(toml: string): string[] {
  readFileSync.mockReturnValue(toml);
  return new CodexSettingsManager("/repo").getSettings().mcpServerNames.sort();
}

describe("CodexSettingsManager MCP server names", () => {
  // Regression: a `[mcp_servers.<name>.env]` table was treated as its own
  // server, so the spawn emitted `mcp_servers.<name>.env.enabled=false`, which
  // sets a boolean on codex's string-typed env map. codex-acp then rejected the
  // whole config, crashed the session, and the host silently ran Claude/Opus.
  it.each([
    {
      name: "collapses a nested sub-table to its parent server and dedupes",
      toml: [
        "[mcp_servers.node_repl]",
        'command = "node"',
        "[mcp_servers.node_repl.env]",
        'FOO = "bar"',
        "[mcp_servers.other]",
        'command = "x"',
      ],
      expected: ["node_repl", "other"],
    },
    {
      name: "collapses a deeply nested sub-table to its parent server",
      toml: ["[mcp_servers.foo.bar.baz]", 'k = "v"'],
      expected: ["foo"],
    },
    {
      name: "keeps the inner name for a double-quoted dotted server key",
      toml: ['[mcp_servers."my.server"]', 'command = "x"'],
      expected: ["my.server"],
    },
    {
      name: "keeps the inner name for a single-quoted dotted server key",
      toml: ["[mcp_servers.'my.server']", 'command = "x"'],
      expected: ["my.server"],
    },
    {
      name: "returns no servers when none are declared",
      toml: ['model = "gpt-5.5"'],
      expected: [],
    },
  ])("$name", ({ toml, expected }) => {
    expect(serverNamesFor(toml.join("\n"))).toEqual(expected);
  });
});
