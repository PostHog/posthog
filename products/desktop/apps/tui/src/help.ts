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
      { keys: "Ctrl+K", does: "Search your chats (Cmd+K too)" },
      { keys: "Ctrl+C Ctrl+C", does: "Close the chat; on the last pane, quit" },
      { keys: "Enter", does: "Send; mid-turn it steers the agent" },
      { keys: "Esc", does: "Stop the agent; twice clears the composer" },
      { keys: "Ctrl+V", does: "Paste an image from the clipboard" },
      { keys: "!", does: "Run a shell command where the agent runs" },
    ],
  },
  {
    title: "Panes",
    rows: [
      { keys: "Ctrl+\\", does: "Split side by side" },
      { keys: "Ctrl+|", does: "Split stacked" },
      { keys: "Ctrl+B", does: "Narrow the sidebar to its logo (Cmd+B too)" },
      { keys: "↑ ↓", does: "Step through the sidebar's chats" },
    ],
  },
  {
    title: "Claude Code chats",
    rows: [
      { keys: "Ctrl+]", does: "Step the permission mode" },
      { keys: "Ctrl+}", does: "Step it back" },
    ],
  },
  {
    title: "App",
    rows: [
      { keys: "Ctrl+;", does: "Settings" },
      { keys: "Ctrl+R", does: "Reload the app's code" },
      { keys: "Ctrl+Q", does: "Quit" },
      {
        keys: "/",
        does: "Slash commands: /model, /billing, /repo, /local, /cloud and more",
      },
    ],
  },
];
