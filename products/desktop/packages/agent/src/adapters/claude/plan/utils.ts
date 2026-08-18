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

export function isSubagentPlanFilePath(filePath: string): boolean {
  return /-agent-[0-9a-f]{8,}\.md$/i.test(path.basename(filePath));
}

export function isPlanReady(plan: string | undefined): boolean {
  if (!plan) return false;
  const trimmed = plan.trim();
  if (trimmed.length < 40) return false;
  return /(^|\n)#{1,6}\s+\S/.test(trimmed);
}

export async function readPlanFile(filePath: string): Promise<string | null> {
  try {
    const content = await fs.readFile(filePath, "utf8");
    if (!content.trim()) {
      return null;
    }
    return content;
  } catch {
    return null;
  }
}
