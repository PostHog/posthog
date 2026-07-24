import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentConfig } from "./agents";
import { discoverAgents, gateProjectAgents } from "./discovery";

describe("discoverAgents", () => {
  let tmpProject: string;

  beforeEach(() => {
    tmpProject = fs.mkdtempSync(
      path.join(os.tmpdir(), "posthog-subagent-discovery-"),
    );
  });

  afterEach(() => {
    fs.rmSync(tmpProject, { recursive: true, force: true });
  });

  it("returns only bundled agents for scope 'bundled'", () => {
    const result = discoverAgents(tmpProject, "bundled");
    expect(result.agents.every((a) => a.source === "bundled")).toBe(true);
    expect(result.agents.map((a) => a.name)).toContain("Explore");
  });

  it("returns nothing for scope 'project' when there is no .pi/agents dir", () => {
    const result = discoverAgents(tmpProject, "project");
    expect(result.agents).toEqual([]);
    expect(result.projectAgentsDir).toBeNull();
  });

  it("loads project agents and merges them with bundled ones for scope 'both'", () => {
    const agentsDir = path.join(tmpProject, ".pi", "agents");
    fs.mkdirSync(agentsDir, { recursive: true });
    fs.writeFileSync(
      path.join(agentsDir, "custom.md"),
      "---\nname: custom\ndescription: A custom project agent\ntools: read, grep\n---\nBe a custom agent.\n",
    );

    const result = discoverAgents(tmpProject, "both");
    const custom = result.agents.find((a) => a.name === "custom");
    expect(custom).toMatchObject({
      source: "project",
      description: "A custom project agent",
      tools: ["read", "grep"],
    });
    expect(result.agents.some((a) => a.name === "Explore")).toBe(true);
    expect(result.projectAgentsDir).toBe(agentsDir);
  });

  it("lets a project agent override a bundled agent of the same name", () => {
    const agentsDir = path.join(tmpProject, ".pi", "agents");
    fs.mkdirSync(agentsDir, { recursive: true });
    fs.writeFileSync(
      path.join(agentsDir, "explore.md"),
      "---\nname: Explore\ndescription: Project-overridden explore\n---\nOverridden.\n",
    );

    const result = discoverAgents(tmpProject, "both");
    const explore = result.agents.find((a) => a.name === "Explore");
    expect(explore?.source).toBe("project");
    expect(explore?.description).toBe("Project-overridden explore");
  });

  it("ignores markdown files missing required frontmatter", () => {
    const agentsDir = path.join(tmpProject, ".pi", "agents");
    fs.mkdirSync(agentsDir, { recursive: true });
    fs.writeFileSync(
      path.join(agentsDir, "broken.md"),
      "---\nname: broken\n---\nNo description.\n",
    );

    const result = discoverAgents(tmpProject, "project");
    expect(result.agents.find((a) => a.name === "broken")).toBeUndefined();
  });
});

const projectAgent: AgentConfig = {
  name: "custom",
  description: "custom",
  systemPrompt: "custom",
  source: "project",
};

function makeCtx(
  overrides: { hasUI?: boolean; trusted?: boolean; confirm?: boolean } = {},
) {
  return {
    hasUI: overrides.hasUI ?? true,
    isProjectTrusted: vi.fn(() => overrides.trusted ?? true),
    ui: { confirm: vi.fn(async () => overrides.confirm ?? true) },
  };
}

describe("gateProjectAgents", () => {
  it("allows immediately when no project agents were requested", async () => {
    const ctx = makeCtx({ trusted: false });
    const result = await gateProjectAgents({
      ctx,
      requestedAgents: [],
      projectAgentsDir: null,
      confirmProjectAgents: undefined,
    });
    expect(result.allowed).toBe(true);
    expect(ctx.isProjectTrusted).not.toHaveBeenCalled();
  });

  it("refuses when the project is not trusted, regardless of other flags", async () => {
    const ctx = makeCtx({ trusted: false });
    const result = await gateProjectAgents({
      ctx,
      requestedAgents: [projectAgent],
      projectAgentsDir: "/repo/.pi/agents",
      confirmProjectAgents: false,
    });
    expect(result.allowed).toBe(false);
    expect(result.reason).toMatch(/not trusted/);
  });

  it("prompts via ctx.ui.confirm when trusted and UI is available", async () => {
    const ctx = makeCtx({ trusted: true, hasUI: true, confirm: true });
    const result = await gateProjectAgents({
      ctx,
      requestedAgents: [projectAgent],
      projectAgentsDir: "/repo/.pi/agents",
      confirmProjectAgents: undefined,
    });
    expect(ctx.ui.confirm).toHaveBeenCalledTimes(1);
    expect(result.allowed).toBe(true);
  });

  it("refuses when the user declines the confirm prompt", async () => {
    const ctx = makeCtx({ trusted: true, hasUI: true, confirm: false });
    const result = await gateProjectAgents({
      ctx,
      requestedAgents: [projectAgent],
      projectAgentsDir: "/repo/.pi/agents",
      confirmProjectAgents: undefined,
    });
    expect(result.allowed).toBe(false);
  });

  it("skips the prompt when confirmProjectAgents is explicitly false, with UI available", async () => {
    const ctx = makeCtx({ trusted: true, hasUI: true });
    const result = await gateProjectAgents({
      ctx,
      requestedAgents: [projectAgent],
      projectAgentsDir: "/repo/.pi/agents",
      confirmProjectAgents: false,
    });
    expect(ctx.ui.confirm).not.toHaveBeenCalled();
    expect(result.allowed).toBe(true);
  });

  it("defaults to refusing in headless mode even when trusted", async () => {
    const ctx = makeCtx({ trusted: true, hasUI: false });
    const result = await gateProjectAgents({
      ctx,
      requestedAgents: [projectAgent],
      projectAgentsDir: "/repo/.pi/agents",
      confirmProjectAgents: undefined,
    });
    expect(result.allowed).toBe(false);
    expect(result.reason).toMatch(/without a UI/);
  });

  it("allows in headless mode only with an explicit confirmProjectAgents: false", async () => {
    const ctx = makeCtx({ trusted: true, hasUI: false });
    const result = await gateProjectAgents({
      ctx,
      requestedAgents: [projectAgent],
      projectAgentsDir: "/repo/.pi/agents",
      confirmProjectAgents: false,
    });
    expect(result.allowed).toBe(true);
  });
});
