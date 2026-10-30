import {
  matchesKey,
  truncateToWidth,
  visibleWidth,
  wrapTextWithAnsi,
} from "@earendil-works/pi-tui";

// A bottom sheet: a titled list the user picks from, drawn in place of or above a pane's composer.
export interface SheetItem {
  label: string;
  detail?: string;
  // The item the setting currently holds.
  current?: boolean;
  // Why the item cannot be chosen here; it still shows, greyed out.
  disabled?: string;
}

export interface Sheet {
  title: string;
  description?: string;
  items: SheetItem[];
  footer?: string;
}

export type SheetKey =
  | { kind: "up" | "down" | "choose" | "dismiss" }
  | { kind: "number"; index: number };

const ESC = "\u001b";
const ACCENT = (text: string): string => `${ESC}[34m${text}${ESC}[39m`;
const BOLD = (text: string): string => `${ESC}[1m${text}${ESC}[22m`;
const DIM = (text: string): string => `${ESC}[2m${text}${ESC}[22m`;
const GREEN = (text: string): string => `${ESC}[32m${text}${ESC}[39m`;
const MAX_ITEMS = 10;

export function sheetKey(sequence: string): SheetKey | null {
  if (matchesKey(sequence, "up")) return { kind: "up" };
  if (matchesKey(sequence, "down")) return { kind: "down" };
  if (matchesKey(sequence, "enter")) return { kind: "choose" };
  if (matchesKey(sequence, "escape")) return { kind: "dismiss" };
  if (/^[1-9]$/.test(sequence))
    return { kind: "number", index: Number(sequence) - 1 };
  return null;
}

export function moveCursor(sheet: Sheet, index: number, step: 1 | -1): number {
  return Math.min(sheet.items.length - 1, Math.max(0, index + step));
}

export function renderSheet(
  sheet: Sheet,
  index: number,
  width: number,
  maxItems: number = MAX_ITEMS,
): string[] {
  const numberWidth = String(sheet.items.length).length;
  const labels = sheet.items.map(
    (item, i) =>
      `${String(i + 1).padStart(numberWidth)}. ${item.label}${item.current ? " ✔" : ""}`,
  );
  const labelWidth = Math.max(...labels.map((label) => visibleWidth(label)));
  const count = Math.min(maxItems, sheet.items.length);
  const start = Math.max(
    0,
    Math.min(index - count + 1, sheet.items.length - count),
  );

  const lines = [
    ACCENT("─".repeat(width)),
    "",
    ` ${ACCENT(BOLD(sheet.title))}`,
  ];
  if (sheet.description) {
    for (const line of wrapTextWithAnsi(sheet.description, width - 1)) {
      lines.push(` ${DIM(line)}`);
    }
  }
  lines.push("");
  for (let i = start; i < start + count; i++) {
    const item = sheet.items[i];
    const cursor = i === index ? ACCENT("❯") : " ";
    const padding = " ".repeat(labelWidth - visibleWidth(labels[i]));
    let label = labels[i];
    if (item.current) label = `${label.slice(0, -2)} ${GREEN("✔")}`;
    const detail = [item.detail, item.disabled && `(${item.disabled})`]
      .filter(Boolean)
      .join(" ");
    const text = `${label}${padding}${detail ? `  ${detail}` : ""}`;
    lines.push(
      truncateToWidth(` ${cursor} ${item.disabled ? DIM(text) : text}`, width),
    );
  }
  const hidden = sheet.items.length - count;
  if (hidden > 0) lines.push(DIM(`     … +${hidden} more`));
  if (sheet.footer) lines.push("", ` ${DIM(sheet.footer)}`);
  return lines;
}
