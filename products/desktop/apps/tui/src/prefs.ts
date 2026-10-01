import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type ChatPlace = "local" | "cloud";

export interface Prefs {
  // Where a pane's new chat runs when the pane has no /local or /cloud of its own.
  newChatPlace: ChatPlace;
}

const PREFS_PATH = join(homedir(), ".config", "posthog-tui", "prefs.json");

const DEFAULT_PREFS: Prefs = { newChatPlace: "cloud" };

export function loadPrefs(path: string = PREFS_PATH): Prefs {
  try {
    const saved = JSON.parse(readFileSync(path, "utf8")) as Partial<Prefs>;
    return {
      newChatPlace: saved.newChatPlace === "local" ? "local" : "cloud",
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(prefs: Prefs, path: string = PREFS_PATH): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(prefs));
}
