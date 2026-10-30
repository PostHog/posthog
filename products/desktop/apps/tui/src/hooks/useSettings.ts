import { useRef, useState } from "react";
import {
  clearClaudeToken,
  loadClaudeToken,
  saveClaudeToken,
} from "../claudeToken";
import { messageOf } from "../errors";
import { loadPrefs, savePrefs } from "../prefs";
import { type SettingsView, settingsKey, settingsView } from "../settings";

export interface SettingsState {
  open: boolean;
  view: SettingsView;
  toggle: () => void;
  // Raw key sequences while the settings are open.
  onKey: (sequence: string) => void;
}

// The full-screen settings: each change is saved as it is made, so closing loses nothing.
export function useSettings(): SettingsState {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<SettingsView>(() =>
    settingsView(false, false),
  );
  // Keys arrive in bursts before React renders, so each one reads the view the last one left.
  const latest = useRef(view);
  const update = (next: SettingsView): void => {
    latest.current = next;
    setView(next);
  };

  return {
    open,
    view,
    toggle: () => {
      if (!open)
        update(
          settingsView(loadPrefs().localClaudePlan, loadClaudeToken() !== null),
        );
      setOpen(!open);
    },
    onKey: (sequence) => {
      const { view: next, effect } = settingsKey(latest.current, sequence);
      update(next);
      if (!effect) return;
      try {
        if (effect.kind === "setPlan")
          savePrefs({ localClaudePlan: effect.on });
        else if (effect.kind === "saveToken") saveClaudeToken(effect.token);
        else if (effect.kind === "clearToken") clearClaudeToken();
        else setOpen(false);
      } catch (error) {
        update({ ...next, error: `Couldn't save: ${messageOf(error)}` });
      }
    },
  };
}
