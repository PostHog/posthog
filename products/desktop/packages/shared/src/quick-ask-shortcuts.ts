/**
 * Global shortcut presets for the quick-ask panel. A fixed allowlist rather
 * than a free-form recorder: the main process validates against it, and every
 * entry is known to register cleanly as an Electron accelerator.
 */

export interface QuickAskShortcutPreset {
  /** Electron accelerator string (Alt = Option on macOS). */
  accelerator: string;
  /** Label shown on macOS. */
  macLabel: string;
  /** Label shown on Windows/Linux. */
  otherLabel: string;
}

export const QUICK_ASK_SHORTCUT_PRESETS: readonly QuickAskShortcutPreset[] = [
  {
    accelerator: "Alt+Space",
    macLabel: "⌥ Space",
    otherLabel: "Alt+Space",
  },
  {
    accelerator: "Control+Space",
    macLabel: "⌃ Space",
    otherLabel: "Ctrl+Space",
  },
  {
    accelerator: "Alt+P",
    macLabel: "⌥ P",
    otherLabel: "Alt+P",
  },
  {
    accelerator: "CommandOrControl+Shift+Space",
    macLabel: "⌘ ⇧ Space",
    otherLabel: "Ctrl+Shift+Space",
  },
];

export const QUICK_ASK_DEFAULT_SHORTCUT =
  QUICK_ASK_SHORTCUT_PRESETS[0].accelerator;

export function isQuickAskShortcut(accelerator: string): boolean {
  return QUICK_ASK_SHORTCUT_PRESETS.some(
    (preset) => preset.accelerator === accelerator,
  );
}
