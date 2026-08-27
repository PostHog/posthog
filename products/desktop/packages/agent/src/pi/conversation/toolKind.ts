import type { ToolsOptions } from "@earendil-works/pi-coding-agent";
import type { AgentToolKind } from "@posthog/shared";

export type PiToolName = keyof ToolsOptions;

export const TOOL_KIND_BY_NAME: Record<PiToolName, AgentToolKind> = {
  read: "read",
  edit: "edit",
  write: "edit",
  bash: "execute",
  grep: "search",
  find: "search",
  ls: "read",
};
