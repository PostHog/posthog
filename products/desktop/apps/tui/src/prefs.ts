import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { BILLINGS, type Billing } from "./billing";
import type { ModelChoice } from "./models";

export type ChatPlace = "local" | "cloud";
// Whose chats the sidebar lists under its tabs: the user's own, or the whole team's.
export type ChatScope = "mine" | "all";

export interface PinnedChat {
  id: string;
  title: string;
}

export interface Prefs {
  // Where a pane's new chat runs when the pane has no /local or /cloud of its own.
  newChatPlace: ChatPlace;
  // The sidebar shrunk to its logo's width with Ctrl+B.
  narrowSidebar: boolean;
  // The repositories each pane's new cloud chats clone, by pane id, from /repo.
  paneRepositories: Record<string, string[]>;
  // Who pays for new chats, from /billing.
  billing: Billing;
  // The permission mode new Claude Code chats start in, from /mode.
  claudeMode: string;
  // The last model picked with /model, which new chats start on when their agent offers it.
  lastModel?: ModelChoice;
  // The context donut on the composer's rule, from settings.
  showContext: boolean;
  // Today's briefing in the sidebar and the main view, from settings.
  showToday: boolean;
  // The first run's sign-in sheet has been shown.
  welcomed: boolean;
  // Cloud Claude Code and Codex chats reach this machine's MCP servers through the TUI, from /mcp.
  relayLocalMcp: boolean;
  // Chats pinned above the workspaces with Ctrl+P, with the name they had so they show before the list loads.
  pinnedChats: PinnedChat[];
  // The tab the sidebar's chat list is on.
  chatScope: ChatScope;
}

const modelOf = (saved: unknown): ModelChoice | undefined => {
  const model = saved as Partial<ModelChoice> | null;
  return typeof model?.provider === "string" &&
    typeof model.id === "string" &&
    typeof model.name === "string"
    ? { provider: model.provider, id: model.id, name: model.name }
    : undefined;
};

const PREFS_PATH = join(homedir(), ".config", "posthog-tui", "prefs.json");

const DEFAULT_PREFS: Prefs = {
  newChatPlace: "cloud",
  narrowSidebar: false,
  paneRepositories: {},
  billing: "posthog",
  claudeMode: "auto",
  showContext: false,
  showToday: true,
  welcomed: false,
  relayLocalMcp: false,
  pinnedChats: [],
  chatScope: "mine",
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
      billing:
        BILLINGS.find((billing) => billing === saved.billing) ?? "posthog",
      claudeMode:
        typeof saved.claudeMode === "string" ? saved.claudeMode : "auto",
      ...(modelOf(saved.lastModel) && { lastModel: modelOf(saved.lastModel) }),
      showContext: saved.showContext === true,
      showToday: saved.showToday !== false,
      welcomed: saved.welcomed === true,
      relayLocalMcp: saved.relayLocalMcp === true,
      pinnedChats: Array.isArray(saved.pinnedChats)
        ? saved.pinnedChats.filter(
            (chat): chat is PinnedChat =>
              typeof chat?.id === "string" && typeof chat?.title === "string",
          )
        : [],
      chatScope: saved.chatScope === "all" ? "all" : "mine",
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
