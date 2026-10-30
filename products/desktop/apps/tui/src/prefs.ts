import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type ChatPlace = "local" | "cloud";

export interface Prefs {
  // Where a pane's new chat runs when the pane has no /local or /cloud of its own.
  newChatPlace: ChatPlace;
  // The sidebar shrunk to its logo's width with Ctrl+B.
  narrowSidebar: boolean;
}

const PREFS_PATH = join(homedir(), ".config", "posthog-tui", "prefs.json");

const DEFAULT_PREFS: Prefs = { newChatPlace: "cloud", narrowSidebar: false };

export function loadPrefs(path: string = PREFS_PATH): Prefs {
  try {
    const saved = JSON.parse(readFileSync(path, "utf8")) as Partial<Prefs>;
    return {
      newChatPlace: saved.newChatPlace === "local" ? "local" : "cloud",
      narrowSidebar: saved.narrowSidebar === true,
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

// Saves the given preferences over the ones on disk, so each setting can be saved on its own.
export function savePrefs(
  prefs: Partial<Prefs>,
  path: string = PREFS_PATH,
): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify({ ...loadPrefs(path), ...prefs }));
}
