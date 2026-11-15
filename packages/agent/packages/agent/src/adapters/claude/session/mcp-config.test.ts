import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  loadUserClaudeJsonMcpServerEntries,
  loadUserClaudeJsonMcpServers,
} from "./mcp-config";

describe("loadUserClaudeJsonMcpServers", () => {
  let tmpHome: string;

  beforeEach(() => {
    tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "claude-json-test-"));
  });

  afterEach(() => {
    fs.rmSync(tmpHome, { recursive: true, force: true });
  });

  it.each([
    { name: "~/.claude.json is missing", setup: () => undefined },
    {
      name: "~/.claude.json contains invalid JSON",
      setup: (home: string) =>
        fs.writeFileSync(path.join(home, ".claude.json"), "not json"),
    },
  ])("returns empty when $name", ({ setup }) => {
    setup(tmpHome);
    expect(
      loadUserClaudeJsonMcpServers("/some/cwd", undefined, tmpHome),
    ).toEqual({});
  });

  it("returns top-level mcpServers", () => {
    const cfg = {
      mcpServers: {
        top: { type: "stdio", command: "npx", args: ["pkg"] },
      },
    };
    fs.writeFileSync(path.join(tmpHome, ".claude.json"), JSON.stringify(cfg));
    const servers = loadUserClaudeJsonMcpServers(
      "/some/cwd",
      undefined,
      tmpHome,
    );
    expect(servers.top).toBeDefined();
  });

  it("returns project-scoped mcpServers when cwd matches a project entry", () => {
    const cwd = "/Users/jane/proj";
    const cfg = {
      projects: {
        [cwd]: {
          mcpServers: {
            playwright: {
              type: "stdio",
              command: "npx",
              args: ["@playwright/mcp@latest"],
            },
          },
        },
      },
    };
    fs.writeFileSync(path.join(tmpHome, ".claude.json"), JSON.stringify(cfg));
    const servers = loadUserClaudeJsonMcpServers(cwd, undefined, tmpHome);
    expect(servers.playwright).toBeDefined();
  });

  it("project-scoped servers override top-level on key collision", () => {
    const cwd = "/Users/jane/proj";
    const cfg = {
      mcpServers: {
        shared: { type: "stdio", command: "global", args: [] },
      },
      projects: {
        [cwd]: {
          mcpServers: {
            shared: { type: "stdio", command: "scoped", args: [] },
          },
        },
      },
    };
    fs.writeFileSync(path.join(tmpHome, ".claude.json"), JSON.stringify(cfg));
    const servers = loadUserClaudeJsonMcpServers(cwd, undefined, tmpHome);
    expect((servers.shared as { command: string }).command).toBe("scoped");
  });

  it("ignores CLAUDE_CONFIG_DIR redirect (reads real ~/.claude.json)", () => {
    const altDir = fs.mkdtempSync(path.join(os.tmpdir(), "alt-claude-"));
    fs.writeFileSync(
      path.join(altDir, ".claude.json"),
      JSON.stringify({
        mcpServers: { wrong: { type: "stdio", command: "x" } },
      }),
    );
    fs.writeFileSync(
      path.join(tmpHome, ".claude.json"),
      JSON.stringify({
        mcpServers: { right: { type: "stdio", command: "y" } },
      }),
    );
    const original = process.env.CLAUDE_CONFIG_DIR;
    process.env.CLAUDE_CONFIG_DIR = altDir;
    try {
      const servers = loadUserClaudeJsonMcpServers("/cwd", undefined, tmpHome);
      expect(servers.right).toBeDefined();
      expect(servers.wrong).toBeUndefined();
    } finally {
      if (original === undefined) delete process.env.CLAUDE_CONFIG_DIR;
      else process.env.CLAUDE_CONFIG_DIR = original;
      fs.rmSync(altDir, { recursive: true, force: true });
    }
  });
});

describe("loadUserClaudeJsonMcpServerEntries", () => {
  let tmpHome: string;

  beforeEach(() => {
    tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "claude-json-test-"));
  });

  afterEach(() => {
    fs.rmSync(tmpHome, { recursive: true, force: true });
  });

  it("tags each server with its scope and lets project entries win", () => {
    const cwd = "/Users/jane/proj";
    const cfg = {
      mcpServers: {
        shared: { type: "stdio", command: "global" },
        userOnly: { type: "http", url: "https://a.example.com" },
      },
      projects: {
        [cwd]: {
          mcpServers: {
            shared: { type: "stdio", command: "scoped" },
          },
        },
      },
    };
    fs.writeFileSync(path.join(tmpHome, ".claude.json"), JSON.stringify(cfg));

    const entries = loadUserClaudeJsonMcpServerEntries(cwd, undefined, tmpHome);

    expect(entries).toEqual([
      {
        name: "shared",
        scope: "project",
        config: { type: "stdio", command: "scoped" },
      },
      {
        name: "userOnly",
        scope: "user",
        config: { type: "http", url: "https://a.example.com" },
      },
    ]);
  });

  it("returns only user-scoped servers when cwd is omitted", () => {
    const cfg = {
      mcpServers: { top: { type: "http", url: "https://a.example.com" } },
      projects: {
        "/proj": {
          mcpServers: { scoped: { type: "stdio", command: "x" } },
        },
      },
    };
    fs.writeFileSync(path.join(tmpHome, ".claude.json"), JSON.stringify(cfg));

    const entries = loadUserClaudeJsonMcpServerEntries(
      undefined,
      undefined,
      tmpHome,
    );
    expect(entries.map((e) => e.name)).toEqual(["top"]);
  });

  it("returns empty when ~/.claude.json is missing or invalid", () => {
    expect(
      loadUserClaudeJsonMcpServerEntries("/cwd", undefined, tmpHome),
    ).toEqual([]);
    fs.writeFileSync(path.join(tmpHome, ".claude.json"), "not json");
    expect(
      loadUserClaudeJsonMcpServerEntries("/cwd", undefined, tmpHome),
    ).toEqual([]);
  });
});
