import { readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  AGENT_FLOW_SKILL_FILE,
  type AgentFlowDefinition,
  parseAgentFlowSkillFile,
} from "@posthog/shared";

export interface FlowSkill {
  flow: AgentFlowDefinition;
  dirName: string;
}

/** Skill roots that can hold flow skills (a directory with a flow.json). */
function flowSkillRoots(cwd: string): string[] {
  return [
    join(homedir(), ".claude", "skills"),
    join(homedir(), ".agents", "skills"),
    join(cwd, ".agents", "skills"),
  ];
}

export function listFlowSkills(cwd: string): FlowSkill[] {
  const found: FlowSkill[] = [];
  const seen = new Set<string>();
  for (const root of flowSkillRoots(cwd)) {
    let entries: string[];
    try {
      entries = readdirSync(root);
    } catch {
      continue;
    }
    for (const dirName of entries) {
      if (seen.has(dirName)) {
        continue;
      }
      let content: string;
      try {
        content = readFileSync(
          join(root, dirName, AGENT_FLOW_SKILL_FILE),
          "utf8",
        );
      } catch {
        continue;
      }
      const flow = parseAgentFlowSkillFile(content);
      if (flow) {
        seen.add(dirName);
        found.push({ flow, dirName });
      }
    }
  }
  return found;
}

/** Finds a flow skill by its skill folder name or its display name. */
export function findFlowSkill(query: string, cwd: string): FlowSkill | null {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return null;
  }
  const skills = listFlowSkills(cwd);
  return (
    skills.find((skill) => skill.dirName.toLowerCase() === needle) ??
    skills.find((skill) => skill.flow.name.toLowerCase() === needle) ??
    null
  );
}
