import type { PromptRequest } from "@agentclientprotocol/sdk";

/** True when a prompt chunk is a bare `/<skillName> [args]` invocation. */
export function isLocalSkillCommandChunk(
  chunk: PromptRequest["prompt"][number],
  skillName: string,
): boolean {
  if (chunk.type !== "text") {
    return false;
  }
  const match = chunk.text.trim().match(/^\/([^\s]+)(?:\s+[\s\S]*)?$/);
  return match?.[1] === skillName;
}
