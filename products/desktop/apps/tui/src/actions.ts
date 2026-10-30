import type { Sheet } from "./sheet";
import type { ShowAction, TranscriptLine } from "./transcript";

export type ActionsLine = Extract<TranscriptLine, { kind: "actions" }>;

// The buttons from the agent's latest offer, until the user sends another message.
export function openActions(lines: TranscriptLine[]): ActionsLine | null {
  for (let index = lines.length - 1; index >= 0; index--) {
    const line = lines[index];
    if (line.kind === "user") return null;
    if (line.kind === "actions") return line;
  }
  return null;
}

// Compose prefills a new chat, which the TUI can do; the other kinds open desktop screens.
export function canRun(action: ShowAction): boolean {
  return action.kind === "compose";
}

export function actionsSheet(offer: ActionsLine): Sheet {
  return {
    title: "Suggested actions",
    items: offer.actions.map((action) => ({
      label: action.label,
      detail: action.kind === "compose" ? action.description : undefined,
      disabled: canRun(action) ? undefined : "PostHog Desktop only",
    })),
    footer: "Enter to open · Esc to dismiss · or type a reply",
  };
}
