import type { Adapter } from "./adapter";
import type { ExecutionMode } from "./exec-types";

export interface CodexModePreset {
  id: "plan" | "read-only" | "auto" | "full-access";
  name: string;
  description: string;
}

/**
 * The codex mode presets every picker shows (task creation and live session).
 * One copy so the pickers (agent execution-mode.ts, core executionModes.ts)
 * and the adapter's behavioral map (codex-app-server session-config.ts) cannot
 * drift; each consumer owns only its own gating and policy mapping.
 */
export const CODEX_MODE_PRESETS: readonly CodexModePreset[] = [
  {
    id: "plan",
    name: "Plan",
    description: "Plan first — inspect and propose; makes no changes",
  },
  {
    id: "read-only",
    name: "Read only",
    description: "Read-only — can inspect but not modify files",
  },
  {
    id: "auto",
    name: "Auto",
    description: "Edits the workspace; asks before risky operations",
  },
  {
    id: "full-access",
    name: "Full access",
    description: "Auto-approves all operations",
  },
];

const CLAUDE_CLOUD_PERMISSION_MODES = [
  "default",
  "acceptEdits",
  "plan",
  "bypassPermissions",
  "auto",
] as const;

const CODEX_CLOUD_PERMISSION_MODES = [
  "plan",
  "auto",
  "read-only",
  "full-access",
] as const;

type ClaudeCloudPermissionMode = (typeof CLAUDE_CLOUD_PERMISSION_MODES)[number];
type CodexCloudPermissionMode = (typeof CODEX_CLOUD_PERMISSION_MODES)[number];

function isClaudeCloudPermissionMode(
  mode: ExecutionMode,
): mode is ClaudeCloudPermissionMode {
  return (CLAUDE_CLOUD_PERMISSION_MODES as readonly string[]).includes(mode);
}

function isCodexCloudPermissionMode(
  mode: ExecutionMode,
): mode is CodexCloudPermissionMode {
  return (CODEX_CLOUD_PERMISSION_MODES as readonly string[]).includes(mode);
}

// Translate presets that only exist on the other adapter to the nearest permission ceiling.
const CODEX_CLOUD_MODE_FALLBACKS: Record<
  Exclude<ClaudeCloudPermissionMode, "auto" | "plan">,
  CodexCloudPermissionMode
> = {
  default: "auto",
  acceptEdits: "auto",
  bypassPermissions: "full-access",
};

const CLAUDE_CLOUD_MODE_FALLBACKS: Record<
  Exclude<CodexCloudPermissionMode, "auto" | "plan">,
  ClaudeCloudPermissionMode
> = {
  "read-only": "plan",
  "full-access": "bypassPermissions",
};

export function resolveCloudInitialPermissionMode(
  adapter: Adapter,
  mode: ExecutionMode,
): ExecutionMode {
  if (adapter === "codex") {
    if (isCodexCloudPermissionMode(mode)) return mode;
    return CODEX_CLOUD_MODE_FALLBACKS[mode] ?? "auto";
  }
  if (isClaudeCloudPermissionMode(mode)) return mode;
  return CLAUDE_CLOUD_MODE_FALLBACKS[mode] ?? "default";
}
