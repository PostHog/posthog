import { CODEX_MODE_PRESETS } from "@posthog/shared";

export interface ModeInfo {
  id: string;
  name: string;
  description: string;
}

const availableModes: ModeInfo[] = [
  {
    id: "default",
    name: "Default",
    description: "Standard behavior, prompts for dangerous operations",
  },
  {
    id: "acceptEdits",
    name: "Accept Edits",
    description: "Auto-accept file edit operations",
  },
  {
    id: "plan",
    name: "Plan Mode",
    description: "Planning mode, no actual tool execution",
  },
  {
    id: "bypassPermissions",
    name: "Bypass Permissions",
    description: "Auto-accept all permission requests",
  },
  {
    id: "auto",
    name: "Auto Mode",
    description: "Auto-approve file edits and shell commands",
  },
];

export function getAvailableModes(): ModeInfo[] {
  return availableModes;
}

// The preset literals live in @posthog/shared (one copy for every picker and
// the app-server adapter's CODEX_MODES). Cloud sessions offer all presets,
// including full-access; the agent package applies its own bypass gating.
export function getAvailableCodexModes(): ModeInfo[] {
  return [...CODEX_MODE_PRESETS];
}
