import { SLASH_COMMANDS } from "./composer";

// What /help shows: every key the app takes, grouped, with the slash commands under them.
export interface HelpRow {
  keys: string;
  does: string;
}

export interface HelpGroup {
  title: string;
  rows: HelpRow[];
}

export const HELP: HelpGroup[] = [
  {
    title: "Chats",
    rows: [
      {
        keys: "Ctrl+N",
        does: "New chat: in the focused pane of a split, else the main view",
      },
      {
        keys: "Ctrl+Shift+N",
        does: "New chat in the main view, outside the split",
      },
      { keys: "Ctrl+K", does: "Search your chats (Cmd+K too)" },
      { keys: "Ctrl+Shift+K", does: "Search full screen, even from a split" },
      {
        keys: "Ctrl+C Ctrl+C",
        does: "Close the chat; on the last pane, quit (Ctrl+D too)",
      },
      { keys: "Enter", does: "Send; mid-turn it steers the agent" },
      { keys: "Esc", does: "Stop the agent; twice clears the composer" },
      { keys: "Ctrl+V", does: "Paste an image from the clipboard" },
      { keys: "!", does: "Run a shell command where the agent runs" },
      {
        keys: "Ctrl+M / Ctrl+Shift+M",
        does: "Step a Claude Code chat's permission mode / back",
      },
      {
        keys: "Ctrl+[ / Ctrl+]",
        does: "Back / forward through the chats visited",
      },
    ],
  },
  {
    title: "Panes",
    rows: [
      { keys: "Ctrl+\\", does: "Split side by side" },
      { keys: "Ctrl+|", does: "Split stacked" },
      { keys: "Ctrl+B", does: "Narrow the sidebar to its logo (Cmd+B too)" },
      {
        keys: "Tab",
        does: "Focus the next pane, or the sidebar (Shift+Tab back)",
      },
      { keys: "↑ ↓", does: "Step through the sidebar's chats" },
      { keys: "← →", does: "Fold or unfold the workspace a chat sits in" },
    ],
  },
  {
    title: "App",
    rows: [
      { keys: "Ctrl+;", does: "Settings" },
      { keys: "Ctrl+R", does: "Reload the app's code" },
      { keys: "Ctrl+Q", does: "Quit" },
    ],
  },
];

// Every built-in slash command, from the list the composer suggests, which also says what each does.
export const COMMANDS = SLASH_COMMANDS.map(({ name }) => `/${name}`).join("  ");
