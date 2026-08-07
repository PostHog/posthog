/**
 * Bundled subagent definitions, loaded from this package's own
 * `bundled-agents/*.md` files — the same YAML-frontmatter-plus-markdown-body
 * convention used for project-local `.pi/agents/*.md` overrides (see
 * `discovery.ts`). Bundled and project agents share one loader
 * (`loadAgentsFromDir`): there is exactly one way to define an agent, not a
 * separate hardcoded shape for "ours" vs. "yours".
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { parseFrontmatter } from "@earendil-works/pi-coding-agent";

export type AgentSource = "bundled" | "project";

export interface AgentConfig {
  name: string;
  description: string;
  tools?: string[];
  model?: string;
  systemPrompt: string;
  source: AgentSource;
}

/**
 * Loads every `.md` file in `dir` as an `AgentConfig`: frontmatter (`name`,
 * `description`, `tools`, `model`) plus the markdown body as the system
 * prompt. Files missing `name` or `description` are silently skipped, same
 * as an unreadable directory returns `[]` rather than throwing — a malformed
 * or missing agent file should never break subagent delegation entirely.
 */
export function loadAgentsFromDir(
  dir: string,
  source: AgentSource,
): AgentConfig[] {
  const agents: AgentConfig[] = [];
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return agents;
  }

  for (const entry of entries) {
    if (!entry.name.endsWith(".md")) continue;
    if (!entry.isFile() && !entry.isSymbolicLink()) continue;

    let content: string;
    try {
      content = fs.readFileSync(path.join(dir, entry.name), "utf-8");
    } catch {
      continue;
    }

    const { frontmatter, body } =
      parseFrontmatter<Record<string, string>>(content);
    if (!frontmatter.name || !frontmatter.description) continue;

    const tools = frontmatter.tools
      ?.split(",")
      .map((t: string) => t.trim())
      .filter(Boolean);

    agents.push({
      name: frontmatter.name,
      description: frontmatter.description,
      tools: tools && tools.length > 0 ? tools : undefined,
      model: frontmatter.model,
      systemPrompt: body,
      source,
    });
  }

  return agents;
}

const BUNDLED_AGENTS_DIR = fileURLToPath(
  new URL("./bundled-agents", import.meta.url),
);

/**
 * Re-reads `bundled-agents/*.md` on every call, same as project agents do —
 * these are a handful of tiny files, not worth caching, and it keeps
 * "bundled" and "project" agents going through the identical code path.
 */
export function loadBundledAgents(): AgentConfig[] {
  return loadAgentsFromDir(BUNDLED_AGENTS_DIR, "bundled");
}

export function findBundledAgent(name: string): AgentConfig | undefined {
  return loadBundledAgents().find((agent) => agent.name === name);
}

export function listBundledAgentNames(): string[] {
  return loadBundledAgents().map((agent) => agent.name);
}
