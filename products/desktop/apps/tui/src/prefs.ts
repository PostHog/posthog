import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type ChatPlace = "local" | "cloud";

export interface Prefs {
  // Where a pane's new chat runs when the pane has no /local or /cloud of its own.
  newChatPlace: ChatPlace;
  // The sidebar shrunk to its logo's width with Ctrl+B.
  narrowSidebar: boolean;
  // The repositories each pane's new cloud chats clone, by pane id, from /repo.
  paneRepositories: Record<string, string[]>;
  // New local chats run on the user's own ChatGPT plan, after a login from settings.
  localChatgptPlan: boolean;
  // New cloud chats run Claude Code on the user's own Claude plan, with the token from settings.
  cloudClaudePlan: boolean;
}

const PREFS_PATH = join(homedir(), ".config", "posthog-tui", "prefs.json");

const DEFAULT_PREFS: Prefs = {
  newChatPlace: "cloud",
  narrowSidebar: false,
  paneRepositories: {},
  localChatgptPlan: false,
  cloudClaudePlan: false,
};

const repositoriesOf = (saved: unknown): Record<string, string[]> =>
  saved && typeof saved === "object"
    ? Object.fromEntries(
        Object.entries(saved).filter(
          (entry): entry is [string, string[]] =>
            Array.isArray(entry[1]) &&
            entry[1].every((repo) => typeof repo === "string"),
        ),
      )
    : {};

export function loadPrefs(path: string = PREFS_PATH): Prefs {
  try {
    const saved = JSON.parse(readFileSync(path, "utf8")) as Partial<Prefs>;
    return {
      newChatPlace: saved.newChatPlace === "local" ? "local" : "cloud",
      narrowSidebar: saved.narrowSidebar === true,
      paneRepositories: repositoriesOf(saved.paneRepositories),
      localChatgptPlan: saved.localChatgptPlan === true,
      cloudClaudePlan: saved.cloudClaudePlan === true,
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
