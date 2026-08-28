import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AgentConfig } from "./agents";
import { applyAgentOverrides, loadSubagentSettings } from "./settings";

const agent: AgentConfig = {
  name: "worker",
  description: "test agent",
  systemPrompt: "test",
  source: "bundled",
};

describe("applyAgentOverrides", () => {
  it("returns the agent unchanged when there are no settings", () => {
    const effective = applyAgentOverrides(agent, {});
    expect(effective.model).toBeUndefined();
    expect(effective.tools).toBeUndefined();
    expect(effective.thinking).toBeUndefined();
    expect(effective.fallbackModels).toBeUndefined();
  });

  it("prefers a per-agent override over the agent's own baked-in model", () => {
    const pinned: AgentConfig = { ...agent, model: "anthropic/haiku" };
    const effective = applyAgentOverrides(pinned, {
      agentOverrides: { worker: { model: "openai/gpt-5" } },
    });
    expect(effective.model).toBe("openai/gpt-5");
  });

  it("falls back to the agent's own baked-in model when there's no override", () => {
    const pinned: AgentConfig = { ...agent, model: "anthropic/haiku" };
    const effective = applyAgentOverrides(pinned, {});
    expect(effective.model).toBe("anthropic/haiku");
  });

  it("parses a comma-separated tools override", () => {
    const effective = applyAgentOverrides(agent, {
      agentOverrides: { worker: { tools: "read, grep ,find" } },
    });
    expect(effective.tools).toEqual(["read", "grep", "find"]);
  });

  it("forces thinking off when settings.disableThinking is set, ignoring a per-agent thinking override", () => {
    const effective = applyAgentOverrides(agent, {
      disableThinking: true,
      agentOverrides: { worker: { thinking: "high" } },
    });
    expect(effective.thinking).toBe("off");
  });

  it("passes through fallbackModels from a per-agent override", () => {
    const effective = applyAgentOverrides(agent, {
      agentOverrides: { worker: { fallbackModels: ["anthropic/haiku"] } },
    });
    expect(effective.fallbackModels).toEqual(["anthropic/haiku"]);
  });
});

describe("loadSubagentSettings", () => {
  let originalHome: string | undefined;
  let tmpHome: string;
  let tmpProject: string;

  beforeEach(() => {
    originalHome = process.env.HOME;
    tmpHome = fs.mkdtempSync(
      path.join(os.tmpdir(), "posthog-subagent-settings-home-"),
    );
    tmpProject = fs.mkdtempSync(
      path.join(os.tmpdir(), "posthog-subagent-settings-project-"),
    );
    process.env.HOME = tmpHome;
  });

  afterEach(() => {
    process.env.HOME = originalHome;
    fs.rmSync(tmpHome, { recursive: true, force: true });
    fs.rmSync(tmpProject, { recursive: true, force: true });
  });

  it("returns an empty object when no settings files exist", () => {
    expect(loadSubagentSettings(tmpProject)).toEqual({ agentOverrides: {} });
  });

  it("tolerates invalid JSON without throwing", () => {
    const dir = path.join(tmpHome, ".pi", "agent");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "settings.json"), "{ not valid json");
    expect(() => loadSubagentSettings(tmpProject)).not.toThrow();
  });

  it("merges project settings over user settings, deep-merging agentOverrides", () => {
    const userDir = path.join(tmpHome, ".pi", "agent");
    fs.mkdirSync(userDir, { recursive: true });
    fs.writeFileSync(
      path.join(userDir, "settings.json"),
      JSON.stringify({
        subagents: {
          agentOverrides: { scout: { model: "anthropic/haiku" } },
        },
      }),
    );

    const projectConfigDir = path.join(tmpProject, ".pi");
    fs.mkdirSync(projectConfigDir, { recursive: true });
    fs.writeFileSync(
      path.join(projectConfigDir, "settings.json"),
      JSON.stringify({
        subagents: {
          agentOverrides: { worker: { model: "openai/gpt-5" } },
        },
      }),
    );

    const trustedSettings = loadSubagentSettings(tmpProject, true);
    expect(trustedSettings.agentOverrides?.scout?.model).toBe(
      "anthropic/haiku",
    );
    expect(trustedSettings.agentOverrides?.worker?.model).toBe("openai/gpt-5");

    // Untrusted (or omitted, default false): project settings are ignored
    // entirely, not merged — only the user-scope override survives.
    const untrustedSettings = loadSubagentSettings(tmpProject);
    expect(untrustedSettings.agentOverrides?.scout?.model).toBe(
      "anthropic/haiku",
    );
    expect(untrustedSettings.agentOverrides?.worker).toBeUndefined();
  });

  it("never reads project settings.json when the project isn't trusted, even without a user settings file", () => {
    const projectConfigDir = path.join(tmpProject, ".pi");
    fs.mkdirSync(projectConfigDir, { recursive: true });
    fs.writeFileSync(
      path.join(projectConfigDir, "settings.json"),
      JSON.stringify({
        subagents: {
          agentOverrides: { oracle: { tools: "read,grep,find,ls,bash,write" } },
        },
      }),
    );

    expect(loadSubagentSettings(tmpProject, false)).toEqual({
      agentOverrides: {},
    });
    expect(
      loadSubagentSettings(tmpProject, true).agentOverrides?.oracle?.tools,
    ).toBe("read,grep,find,ls,bash,write");
  });
});
