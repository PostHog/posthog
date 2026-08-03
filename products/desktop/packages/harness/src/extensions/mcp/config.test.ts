import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { loadConfig, mergeRawConfigs, parseConfig } from "./config";
import { McpError } from "./errors";

describe("parseConfig", () => {
  it("applies defaults", () => {
    const config = parseConfig(
      { mcpServers: { demo: { command: "node" } } },
      "test",
    );
    expect(config.settings).toEqual({
      toolPrefix: "mcp",
      requestTimeoutMs: 30_000,
      maxRetries: 3,
      searchResultLimit: 15,
    });
    expect(config.mcpServers.demo).toMatchObject({
      command: "node",
      args: [],
      transport: "stdio",
      lifecycle: "lazy",
      directTools: false,
    });
  });

  it("parses an empty object into an empty config", () => {
    const config = parseConfig({}, "test");
    expect(config.mcpServers).toEqual({});
    expect(config.settings.toolPrefix).toBe("mcp");
  });

  it.each([
    [
      "stdio server without command",
      { mcpServers: { bad: { transport: "stdio" } } },
      `"command" is required for stdio transport`,
    ],
    [
      "http server without url",
      { mcpServers: { bad: { transport: "streamable-http" } } },
      `"url" is required for streamable-http transport`,
    ],
    [
      "sse server without url",
      { mcpServers: { bad: { transport: "sse" } } },
      `"url" is required for sse transport`,
    ],
    [
      "invalid url",
      { mcpServers: { bad: { transport: "sse", url: "not-a-url" } } },
      "url",
    ],
    [
      "invalid tool prefix",
      {
        settings: { toolPrefix: "has-dash" },
        mcpServers: { ok: { command: "node" } },
      },
      "toolPrefix must match [a-zA-Z0-9_]",
    ],
    [
      "negative timeout",
      { settings: { requestTimeoutMs: -1 } },
      "requestTimeoutMs",
    ],
  ])("rejects %s", (_label, raw, messageFragment) => {
    expect(() => parseConfig(raw, "test")).toThrowError(McpError);
    expect(() => parseConfig(raw, "test")).toThrowError(
      new RegExp(messageFragment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    );
  });
});

describe("mergeRawConfigs", () => {
  it("project settings and servers override global per key", () => {
    const merged = parseConfig(
      mergeRawConfigs(
        {
          settings: { toolPrefix: "g", maxRetries: 1 },
          mcpServers: {
            shared: { command: "global-cmd" },
            globalOnly: { command: "node" },
          },
        },
        {
          settings: { toolPrefix: "p" },
          mcpServers: {
            shared: { command: "project-cmd" },
            projectOnly: { command: "node" },
          },
        },
      ),
      "merged",
    );
    expect(merged.settings.toolPrefix).toBe("p");
    expect(merged.settings.maxRetries).toBe(1);
    expect(merged.mcpServers.shared?.command).toBe("project-cmd");
    expect(Object.keys(merged.mcpServers).sort()).toEqual([
      "globalOnly",
      "projectOnly",
      "shared",
    ]);
  });
});

describe("loadConfig", () => {
  let dir: string;
  let globalPath: string;
  let projectPath: string;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "mcp-config-"));
    globalPath = join(dir, "global.json");
    projectPath = join(dir, "project.json");
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("returns an empty config when neither file exists", async () => {
    const config = await loadConfig(dir, { globalPath, projectPath });
    expect(config.mcpServers).toEqual({});
  });

  it("loads global config alone", async () => {
    await writeFile(
      globalPath,
      JSON.stringify({ mcpServers: { g: { command: "node" } } }),
    );
    const config = await loadConfig(dir, { globalPath, projectPath });
    expect(Object.keys(config.mcpServers)).toEqual(["g"]);
  });

  it("merges project config over global config", async () => {
    await writeFile(
      globalPath,
      JSON.stringify({
        settings: { toolPrefix: "g" },
        mcpServers: { shared: { command: "global" } },
      }),
    );
    await writeFile(
      projectPath,
      JSON.stringify({ mcpServers: { shared: { command: "project" } } }),
    );
    const config = await loadConfig(dir, { globalPath, projectPath });
    expect(config.settings.toolPrefix).toBe("g");
    expect(config.mcpServers.shared?.command).toBe("project");
  });

  it("ignores project config when includeProject is false", async () => {
    await writeFile(
      projectPath,
      JSON.stringify({ mcpServers: { p: { command: "node" } } }),
    );
    const config = await loadConfig(dir, {
      globalPath,
      projectPath,
      includeProject: false,
    });
    expect(config.mcpServers).toEqual({});
  });

  it("throws McpError with code config for malformed JSON", async () => {
    await writeFile(globalPath, "{ not json");
    await expect(
      loadConfig(dir, { globalPath, projectPath }),
    ).rejects.toMatchObject({ name: "McpError", code: "config" });
  });

  it("throws McpError listing issues for invalid schema", async () => {
    await writeFile(
      globalPath,
      JSON.stringify({ mcpServers: { bad: { transport: "sse" } } }),
    );
    await expect(
      loadConfig(dir, { globalPath, projectPath }),
    ).rejects.toThrowError(/"url" is required for sse transport/);
  });
});
