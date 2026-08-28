/**
 * Global shortcut handling for the quick-ask panel: a free-form recorder in
 * settings, validated here against Electron's accelerator grammar, with
 * presets kept for defaults and fallbacks.
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
    accelerator: "CommandOrControl+Alt+P",
    macLabel: "⌘ ⌥ P",
    otherLabel: "Ctrl+Alt+P",
  },
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

const ACCELERATOR_MODIFIERS = new Set([
  "Command",
  "Cmd",
  "Control",
  "Ctrl",
  "CommandOrControl",
  "CmdOrCtrl",
  "Alt",
  "Option",
  "Shift",
  "Super",
  "Meta",
]);

const ACCELERATOR_KEY_RE =
  /^([A-Z0-9]|F([1-9]|1\d|2[0-4])|Space|Tab|Return|Up|Down|Left|Right|Home|End|PageUp|PageDown|[`\-=[\];',./\\])$/;

/**
 * A recordable accelerator: known modifiers plus one key. A bare or
 * shift-only key would swallow normal typing system-wide, so those pass only
 * for function keys.
 */
export function isValidQuickAskAccelerator(accelerator: string): boolean {
  const parts = accelerator.split("+");
  const key = parts[parts.length - 1];
  const modifiers = parts.slice(0, -1);
  if (!key || !ACCELERATOR_KEY_RE.test(key)) return false;
  if (!modifiers.every((part) => ACCELERATOR_MODIFIERS.has(part))) {
    return false;
  }
  const hasRealModifier = modifiers.some((part) => part !== "Shift");
  return hasRealModifier || /^F\d+$/.test(key);
}

const MAC_MODIFIER_GLYPHS: Record<string, string> = {
  Command: "\u2318",
  Cmd: "\u2318",
  CommandOrControl: "\u2318",
  CmdOrCtrl: "\u2318",
  Control: "\u2303",
  Ctrl: "\u2303",
  Alt: "\u2325",
  Option: "\u2325",
  Shift: "\u21e7",
  Super: "\u2318",
  Meta: "\u2318",
};

/** "CommandOrControl+Shift+Space" -> "\u2318 \u21e7 Space" (mac) or "Ctrl+Shift+Space". */
export function formatAccelerator(accelerator: string, mac: boolean): string {
  const parts = accelerator.split("+");
  if (!mac) {
    return parts
      .map((part) =>
        part === "CommandOrControl" || part === "CmdOrCtrl" ? "Ctrl" : part,
      )
      .join("+");
  }
  return parts.map((part) => MAC_MODIFIER_GLYPHS[part] ?? part).join(" ");
}
