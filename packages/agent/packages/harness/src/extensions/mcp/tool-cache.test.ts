import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { McpServerConfig } from "./config";
import { parseConfig } from "./config";
import { hashServerConfig, McpToolCache } from "./tool-cache";

/** `parseConfig(...).mcpServers.demo`, asserted present (avoids `!`). */
function demoConfig(raw: Record<string, unknown>): McpServerConfig {
  const config = parseConfig({ mcpServers: { demo: raw } }, "test").mcpServers
    .demo;
  if (!config) throw new Error("missing demo config");
  return config;
}

describe("hashServerConfig", () => {
  it("is stable for identical config", () => {
    const config = demoConfig({ command: "node", args: ["a"] });
    expect(hashServerConfig(config)).toBe(hashServerConfig(config));
  });

  it("changes when command/args/url/headers/env change", () => {
    const base = demoConfig({ command: "node", args: ["a"] });
    const changedArgs = demoConfig({ command: "node", args: ["b"] });
    expect(hashServerConfig(base)).not.toBe(hashServerConfig(changedArgs));
  });

  it("is unaffected by non-catalog fields (lifecycle, description)", () => {
    const a = demoConfig({ command: "node", lifecycle: "eager" });
    const b = demoConfig({
      command: "node",
      lifecycle: "lazy",
      description: "x",
    });
    expect(hashServerConfig(a)).toBe(hashServerConfig(b));
  });
});

describe("McpToolCache", () => {
  let dir: string;
  let cache: McpToolCache;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "mcp-tool-cache-"));
    cache = new McpToolCache(join(dir, "cache.json"));
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("returns undefined for an uncached server", async () => {
    expect(await cache.get("missing")).toBeUndefined();
  });

  it("round-trips a written entry", async () => {
    await cache.set("demo", {
      configHash: "abc",
      description: "Demo server",
      tools: [{ name: "mcp_demo_echo", mcpName: "echo", description: "Echo" }],
    });
    const entry = await cache.get("demo");
    expect(entry).toMatchObject({
      configHash: "abc",
      description: "Demo server",
      tools: [{ name: "mcp_demo_echo", mcpName: "echo", description: "Echo" }],
    });
    expect(entry?.cachedAt).toBeGreaterThan(0);
  });

  it("keeps entries for other servers independent", async () => {
    await cache.set("one", { configHash: "h1", tools: [] });
    await cache.set("two", { configHash: "h2", tools: [] });
    expect((await cache.get("one"))?.configHash).toBe("h1");
    expect((await cache.get("two"))?.configHash).toBe("h2");
  });

  it("clear removes only the named server", async () => {
    await cache.set("one", { configHash: "h1", tools: [] });
    await cache.set("two", { configHash: "h2", tools: [] });
    await cache.clear("one");
    expect(await cache.get("one")).toBeUndefined();
    expect(await cache.get("two")).toBeDefined();
  });

  it("getIfCurrent ignores entries whose config hash no longer matches", async () => {
    const config = demoConfig({ command: "node" });
    await cache.set("demo", {
      configHash: "stale-hash",
      tools: [{ name: "mcp_demo_echo", mcpName: "echo", description: "Echo" }],
    });
    expect(await cache.getIfCurrent("demo", config)).toBeUndefined();

    await cache.set("demo", {
      configHash: hashServerConfig(config),
      tools: [{ name: "mcp_demo_echo", mcpName: "echo", description: "Echo" }],
    });
    expect(await cache.getIfCurrent("demo", config)).toBeDefined();
  });

  it("all returns every cached entry", async () => {
    await cache.set("one", { configHash: "h1", tools: [] });
    await cache.set("two", { configHash: "h2", tools: [] });
    expect(Object.keys(await cache.all()).sort()).toEqual(["one", "two"]);
  });
});
