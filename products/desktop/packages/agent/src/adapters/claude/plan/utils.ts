import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";

function getClaudeConfigDir(): string {
  return process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
}

export function getClaudePlansDir(): string {
  return path.join(getClaudeConfigDir(), "plans");
}

export function isClaudePlanFilePath(filePath: string | undefined): boolean {
  if (!filePath) return false;
  const resolved = path.resolve(filePath);
  const plansDir = path.resolve(getClaudePlansDir());
  return resolved === plansDir || resolved.startsWith(plansDir + path.sep);
}

/**
 * Subagents are assigned their own plan file, suffixed with their agent id.
 * Treating one as the session's plan would put a subagent's working notes in
 * front of the user instead of the plan they are being asked to approve.
 */
export function isSubagentPlanFilePath(filePath: string): boolean {
  // Agent ids are long hex strings. Requiring length keeps an ordinary plan name
  // that happens to end in "-agent-<word>" from being mistaken for one.
  return /-agent-[0-9a-f]{8,}\.md$/i.test(path.basename(filePath));
}

export function isPlanReady(plan: string | undefined): boolean {
  if (!plan) return false;
  const trimmed = plan.trim();
  if (trimmed.length < 40) return false;
  return /(^|\n)#{1,6}\s+\S/.test(trimmed);
}

/**
 * The plan file is the source of truth. `ExitPlanMode` has no `plan` parameter,
 * and the CLI has the model build the plan up incrementally with Write then
 * Edit — so only the file on disk holds the current plan.
 */
export async function readPlanFile(filePath: string): Promise<string | null> {
  try {
    const content = await fs.readFile(filePath, "utf8");
    return content.trim() ? content : null;
  } catch {
    return null;
  }
}
