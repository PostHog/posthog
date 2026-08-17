import { useServiceOptional } from "@posthog/di/react";
import {
  KeyboardShortcutsList,
  type LeadingShortcutRow,
} from "@posthog/ui/features/command/KeyboardShortcutsSheet";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useEffect, useState } from "react";

const ACCELERATOR_HOTKEYS: Record<string, string> = {
  CommandOrControl: "mod",
  CmdOrCtrl: "mod",
  Command: "mod",
  Cmd: "mod",
  Meta: "mod",
  Super: "mod",
  Control: "ctrl",
  Ctrl: "ctrl",
  Alt: "alt",
  Option: "alt",
  Shift: "shift",
};

/** "Alt+Space" (Electron accelerator) -> "alt+space" (the sheet's format). */
function acceleratorToHotkey(accelerator: string): string {
  return accelerator
    .split("+")
    .map((part) => ACCELERATOR_HOTKEYS[part] ?? part.toLowerCase())
    .join("+");
}

export function ShortcutsSettings() {
  const client = useServiceOptional<QuickAskSettingsClient>(
    QUICK_ASK_SETTINGS_CLIENT,
  );
  const [state, setState] = useState<QuickAskState | null>(null);

  useEffect(() => {
    if (!client) return;
    let active = true;
    client.getState().then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [client]);

  const quickAskRows: LeadingShortcutRow[] =
    client && state?.enabled && state.active
      ? [
          {
            id: "quick-ask",
            description: "Ask PostHog anywhere",
            keys: acceleratorToHotkey(state.shortcut),
            onEdit: () => openSettings("quick-ask"),
          },
        ]
      : [];

  return <KeyboardShortcutsList leadingGeneralShortcuts={quickAskRows} />;
}
