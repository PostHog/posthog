/**
 * Reads the `subagents` section of pi's settings.json (user + nearest
 * project), merged project-over-user. Tolerant of missing/invalid files —
 * always returns a usable (possibly empty) settings object rather than
 * throwing, since a malformed settings file should never break subagent
 * delegation entirely.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { CONFIG_DIR_NAME, getAgentDir } from "@earendil-works/pi-coding-agent";
import { z } from "zod";
import type { AgentConfig } from "./agents";

const thinkingLevelSchema = z.enum([
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
]);
export type ThinkingLevel = z.infer<typeof thinkingLevelSchema>;

const agentOverrideSchema = z.object({
  model: z.string().optional(),
  thinking: thinkingLevelSchema.optional(),
  tools: z.string().optional(),
  fallbackModels: z.array(z.string()).optional(),
});
export type AgentOverride = z.infer<typeof agentOverrideSchema>;

const modelScopeConfigSchema = z.object({
  enforce: z.boolean().optional(),
  allow: z.array(z.string()).optional(),
});
export type ModelScopeConfig = z.infer<typeof modelScopeConfigSchema>;

const subagentSettingsSchema = z.object({
  disableThinking: z.boolean().optional(),
  agentOverrides: z.record(z.string(), agentOverrideSchema).optional(),
  modelScope: modelScopeConfigSchema.optional(),
});
export type SubagentSettings = z.infer<typeof subagentSettingsSchema>;

const jsonObjectSchema = z.record(z.string(), z.unknown());

function readJsonFile(filePath: string): Record<string, unknown> | undefined {
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const parsed = jsonObjectSchema.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}

function findNearestProjectSettingsFile(cwd: string): string | null {
  let currentDir = cwd;
  for (;;) {
    const candidate = path.join(currentDir, CONFIG_DIR_NAME, "settings.json");
    if (fs.existsSync(candidate)) return candidate;
    const parentDir = path.dirname(currentDir);
    if (parentDir === currentDir) return null;
    currentDir = parentDir;
  }
}

function parseField<T>(schema: z.ZodType<T>, value: unknown): T | undefined {
  const parsed = schema.safeParse(value);
  return parsed.success ? parsed.data : undefined;
}

function extractSubagentSettings(
  raw: Record<string, unknown> | undefined,
): SubagentSettings {
  const section = jsonObjectSchema.safeParse(raw?.subagents);
  if (!section.success) return {};

  // Parse each field on its own so one invalid field cannot discard the
  // others. A mistyped agentOverride must not silently drop a valid enforced
  // modelScope and disable the allow-list.
  return {
    disableThinking: parseField(z.boolean(), section.data.disableThinking),
    agentOverrides: parseField(
      z.record(z.string(), agentOverrideSchema),
      section.data.agentOverrides,
    ),
    modelScope: parseField(modelScopeConfigSchema, section.data.modelScope),
  };
}

function mergeSettings(
  base: SubagentSettings,
  override: SubagentSettings,
): SubagentSettings {
  return {
    disableThinking: override.disableThinking ?? base.disableThinking,
    agentOverrides: { ...base.agentOverrides, ...override.agentOverrides },
    modelScope: override.modelScope ?? base.modelScope,
  };
}

/**
 * Project-local `.pi/settings.json` can widen a bundled agent's tools (e.g.
 * grant a normally read-only agent `bash`/write access) or point it at a
 * different model via `agentOverrides` — the same trust concern as
 * `.pi/agents/*.md` in `discovery.ts`. `projectTrusted` must reflect
 * `ctx.isProjectTrusted()`; project settings are ignored entirely (not just
 * unconfirmed) for untrusted projects, since there's no per-call confirm
 * step for settings the way there is for project agent files.
 */
export function loadSubagentSettings(
  cwd: string,
  projectTrusted = false,
): SubagentSettings {
  const userSettingsPath = path.join(getAgentDir(), "settings.json");
  const userSettings = extractSubagentSettings(readJsonFile(userSettingsPath));

  if (!projectTrusted) return mergeSettings(userSettings, {});

  const projectSettingsPath = findNearestProjectSettingsFile(cwd);
  const projectSettings = projectSettingsPath
    ? extractSubagentSettings(readJsonFile(projectSettingsPath))
    : {};

  return mergeSettings(userSettings, projectSettings);
}

export interface EffectiveAgent extends AgentConfig {
  thinking?: ThinkingLevel;
  fallbackModels?: string[];
}

/**
 * Applies `settings.subagents.agentOverrides[agent.name]` on top of a static
 * `AgentConfig`. Never mutates the input. Model resolution is just two
 * steps from here: this agent's effective `model` (override, or whatever's
 * baked into its frontmatter — possibly nothing), and then `auth.ts`'s
 * implicit inherit-the-parent's-model fallback if that model can't be
 * resolved. There is no separate global default — an agent that wants a
 * specific model pins it in its own frontmatter or gets a per-agent
 * override; nothing silently overrides every agent at once.
 */
export function applyAgentOverrides(
  agent: AgentConfig,
  settings: SubagentSettings,
): EffectiveAgent {
  const override = settings.agentOverrides?.[agent.name];
  const tools = override?.tools
    ?.split(",")
    .map((t) => t.trim())
    .filter(Boolean);

  return {
    ...agent,
    model: override?.model ?? agent.model,
    tools: tools && tools.length > 0 ? tools : agent.tools,
    thinking: settings.disableThinking ? "off" : override?.thinking,
    fallbackModels: override?.fallbackModels,
  };
}
