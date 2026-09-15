/**
 * Merges the bundled agents (`agents.ts`'s `loadBundledAgents()`) with
 * project-local `.pi/agents/*.md` — both read through the same
 * `loadAgentsFromDir` frontmatter loader — and gates running project-sourced
 * agents behind trust + confirmation.
 *
 * Project agents are repo-controlled prompts: a hostile or compromised repo
 * could ship one that instructs the model to exfiltrate secrets or run
 * destructive commands. The gate below is deliberately conservative:
 *
 *  - Untrusted project (`!ctx.isProjectTrusted()`): always refused, no matter
 *    what flags the caller passes.
 *  - Trusted project, interactive/RPC UI available: confirmed via
 *    `ctx.ui.confirm()` unless the caller explicitly passes
 *    `confirmProjectAgents: false`.
 *  - Trusted project, no UI available (print/headless/RPC-without-UI): there
 *    is nobody to confirm through, so project agents are refused *unless* the
 *    caller explicitly passed `confirmProjectAgents: false` — an intentional
 *    opt-in for trusted, non-interactive automation, never a silent default.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import {
  CONFIG_DIR_NAME,
  type ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import {
  type AgentConfig,
  loadAgentsFromDir,
  loadBundledAgents,
} from "./agents";

export type AgentScope = "bundled" | "project" | "both";

export interface AgentDiscoveryResult {
  agents: AgentConfig[];
  projectAgentsDir: string | null;
}

function isDirectory(candidate: string): boolean {
  try {
    return fs.statSync(candidate).isDirectory();
  } catch {
    return false;
  }
}

function findNearestProjectAgentsDir(cwd: string): string | null {
  let currentDir = cwd;
  for (;;) {
    const candidate = path.join(currentDir, CONFIG_DIR_NAME, "agents");
    if (isDirectory(candidate)) return candidate;
    const parentDir = path.dirname(currentDir);
    if (parentDir === currentDir) return null;
    currentDir = parentDir;
  }
}

export function discoverAgents(
  cwd: string,
  scope: AgentScope,
): AgentDiscoveryResult {
  const projectAgentsDir = findNearestProjectAgentsDir(cwd);
  const bundled = scope === "project" ? [] : loadBundledAgents();
  const project =
    scope === "bundled" || !projectAgentsDir
      ? []
      : loadAgentsFromDir(projectAgentsDir, "project");

  const agentMap = new Map<string, AgentConfig>();
  for (const agent of bundled) agentMap.set(agent.name, agent);
  for (const agent of project) agentMap.set(agent.name, agent);

  return { agents: Array.from(agentMap.values()), projectAgentsDir };
}

export interface ProjectAgentGateOptions {
  ctx: Pick<ExtensionContext, "hasUI" | "isProjectTrusted"> & {
    ui: Pick<ExtensionContext["ui"], "confirm">;
  };
  requestedAgents: AgentConfig[];
  projectAgentsDir: string | null;
  /** Caller's explicit choice. `undefined` means "use the default (confirm when possible)". */
  confirmProjectAgents: boolean | undefined;
}

export interface ProjectAgentGateResult {
  allowed: boolean;
  reason?: string;
}

/**
 * Gates running any project-sourced agents in `requestedAgents`. Returns
 * `{ allowed: true }` immediately if none of the requested agents are
 * project-sourced.
 */
export async function gateProjectAgents(
  options: ProjectAgentGateOptions,
): Promise<ProjectAgentGateResult> {
  const { ctx, requestedAgents, projectAgentsDir, confirmProjectAgents } =
    options;
  const projectAgents = requestedAgents.filter(
    (agent) => agent.source === "project",
  );
  if (projectAgents.length === 0) return { allowed: true };

  if (!ctx.isProjectTrusted()) {
    return {
      allowed: false,
      reason:
        "This project is not trusted, so project-local subagents cannot run. Trust the project first.",
    };
  }

  const names = projectAgents.map((agent) => agent.name).join(", ");
  const dir = projectAgentsDir ?? "(unknown)";

  if (!ctx.hasUI) {
    if (confirmProjectAgents === false) return { allowed: true };
    return {
      allowed: false,
      reason: `Refusing to run project-local agents (${names}) without a UI to confirm through. Pass confirmProjectAgents: false explicitly to allow this in trusted, non-interactive contexts.`,
    };
  }

  if (confirmProjectAgents === false) return { allowed: true };

  const ok = await ctx.ui.confirm(
    "Run project-local subagents?",
    `Agents: ${names}\nSource: ${dir}\n\nProject agents are repo-controlled prompts. Only continue for trusted repositories.`,
  );
  return ok
    ? { allowed: true }
    : {
        allowed: false,
        reason: "Canceled: project-local agents not approved.",
      };
}
