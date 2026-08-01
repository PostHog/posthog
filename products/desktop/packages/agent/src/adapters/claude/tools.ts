export {
  CODE_EXECUTION_MODES,
  type CodeExecutionMode,
  getAvailableModes,
  type ModeInfo,
} from "../../execution-mode";

import type { PermissionMode as SdkPermissionMode } from "@anthropic-ai/claude-agent-sdk";
import type { CodeExecutionMode } from "../../execution-mode";
import { isMcpToolReadOnly } from "./mcp/tool-metadata";

export const READ_TOOLS: Set<string> = new Set(["Read", "NotebookRead"]);

export const WRITE_TOOLS: Set<string> = new Set([
  "Edit",
  "Write",
  "NotebookEdit",
]);

export const BASH_TOOLS: Set<string> = new Set([
  "Bash",
  "BashOutput",
  "KillShell",
]);

export const SEARCH_TOOLS: Set<string> = new Set(["Glob", "Grep", "LS"]);

export const WEB_TOOLS: Set<string> = new Set(["WebSearch", "WebFetch"]);

export const AGENT_TOOLS: Set<string> = new Set([
  "Task",
  "Agent",
  "TaskCreate",
  "TaskUpdate",
  "TaskGet",
  "TaskList",
]);

const BASE_ALLOWED_TOOLS = [
  ...READ_TOOLS,
  ...SEARCH_TOOLS,
  ...WEB_TOOLS,
  ...AGENT_TOOLS,
];

const AUTO_ALLOWED_TOOLS: Record<string, Set<string>> = {
  // Auto mode is hands-off: it auto-approves file edits and shell commands on
  // top of the base read/search/web/agent tools. Without WRITE_TOOLS and
  // BASH_TOOLS here, Edit/Write/Bash fall through to a manual prompt on every
  // call, which contradicts what the mode advertises. MCP tools are still gated
  // separately (do_not_use is denied, needs_approval still prompts) in
  // canUseTool, so auto stays narrower than bypassPermissions.
  auto: new Set([...BASE_ALLOWED_TOOLS, ...WRITE_TOOLS, ...BASH_TOOLS]),
  default: new Set(BASE_ALLOWED_TOOLS),
  acceptEdits: new Set([...BASE_ALLOWED_TOOLS, ...WRITE_TOOLS]),
  plan: new Set(BASE_ALLOWED_TOOLS),
};

export function toSdkPermissionMode(
  mode: CodeExecutionMode,
): SdkPermissionMode {
  return mode === "auto" ? "default" : mode;
}

export function isToolAllowedForMode(
  toolName: string,
  mode: CodeExecutionMode,
): boolean {
  if (mode === "bypassPermissions") {
    return true;
  }
  if (AUTO_ALLOWED_TOOLS[mode]?.has(toolName) === true) {
    return true;
  }
  if (isMcpToolReadOnly(toolName)) {
    return true;
  }
  return false;
}
