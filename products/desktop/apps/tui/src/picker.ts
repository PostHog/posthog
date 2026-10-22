import {
  matchesKey,
  truncateToWidth,
  visibleWidth,
} from "@earendil-works/pi-tui";

// A searchable multi-select drawn in place of a pane's composer, such as /repo's repository picker.
export interface Picker {
  title: string;
  description?: string;
  query: string;
  // What the search found for the query.
  results: string[];
  // What is ticked, in the order it was ticked.
  selected: string[];
  index: number;
  loading: boolean;
  error?: string;
}

export type PickerKey =
  | { kind: "up" | "down" | "toggle" | "confirm" | "dismiss" | "erase" }
  | { kind: "type"; text: string };

const ESC = "\u001b";
const ACCENT = (text: string): string => `${ESC}[34m${text}${ESC}[39m`;
const BOLD = (text: string): string => `${ESC}[1m${text}${ESC}[22m`;
const DIM = (text: string): string => `${ESC}[2m${text}${ESC}[22m`;
const GREEN = (text: string): string => `${ESC}[32m${text}${ESC}[39m`;
const MAX_ROWS = 10;

export function openPicker(
  title: string,
  selected: string[],
  description?: string,
): Picker {
  return {
    title,
    description,
    query: "",
    results: [],
    selected,
    index: 0,
    loading: true,
  };
}

// Space ticks, since the names searched for have none; any other printable text goes to the search.
export function pickerKey(sequence: string): PickerKey | null {
  if (matchesKey(sequence, "up")) return { kind: "up" };
  if (matchesKey(sequence, "down")) return { kind: "down" };
  if (matchesKey(sequence, "enter")) return { kind: "confirm" };
  if (matchesKey(sequence, "escape")) return { kind: "dismiss" };
  if (matchesKey(sequence, "backspace")) return { kind: "erase" };
  if (sequence === " ") return { kind: "toggle" };
  const text = sequence.replace(/\s/g, "");
  // biome-ignore lint/suspicious/noControlCharactersInRegex: control bytes mark keys, not text
  if (text && !/[\u0000-\u001f\u007f]/.test(text))
    return { kind: "type", text };
  return null;
}

// Ticked items come first, so they stay in view while the search changes.
export function pickerRows(picker: Picker): string[] {
  return [
    ...picker.selected,
    ...picker.results.filter((item) => !picker.selected.includes(item)),
  ];
}

export function applyPickerKey(
  picker: Picker,
  key: PickerKey,
): Picker | "confirm" | "dismiss" {
  const rows = pickerRows(picker);
  switch (key.kind) {
    case "confirm":
    case "dismiss":
      return key.kind;
    case "up":
    case "down": {
      const step = key.kind === "up" ? -1 : 1;
      const index = Math.min(
        Math.max(0, rows.length - 1),
        Math.max(0, picker.index + step),
      );
      return { ...picker, index };
    }
    case "toggle": {
      const item = rows[picker.index];
      if (!item) return picker;
      const selected = picker.selected.includes(item)
        ? picker.selected.filter((picked) => picked !== item)
        : [...picker.selected, item];
      // The cursor stays on the item it toggled, wherever that item moves to.
      const moved = { ...picker, selected };
      return { ...moved, index: Math.max(0, pickerRows(moved).indexOf(item)) };
    }
    case "erase":
      return picker.query
        ? { ...picker, query: picker.query.slice(0, -1), index: 0 }
        : picker;
    case "type":
      return { ...picker, query: picker.query + key.text, index: 0 };
  }
}

export function renderPicker(picker: Picker, width: number): string[] {
  const rows = pickerRows(picker);
  const count = Math.min(MAX_ROWS, rows.length);
  const start = Math.max(
    0,
    Math.min(picker.index - count + 1, rows.length - count),
  );
  const lines = [
    ACCENT("─".repeat(width)),
    "",
    ` ${ACCENT(BOLD(picker.title))}`,
  ];
  if (picker.description) lines.push(` ${DIM(picker.description)}`);
  lines.push("", ` ${DIM("Search:")} ${picker.query}${ACCENT("▌")}`, "");
  for (let i = start; i < start + count; i++) {
    const item = rows[i];
    const cursor = i === picker.index ? ACCENT("❯") : " ";
    const tick = picker.selected.includes(item) ? GREEN("✔") : DIM("·");
    lines.push(truncateToWidth(` ${cursor} ${tick} ${item}`, width));
  }
  if (rows.length === 0) {
    const empty = picker.loading
      ? "Searching…"
      : (picker.error ?? `Nothing matches "${picker.query}"`);
    lines.push(` ${DIM(empty)}`);
  } else if (rows.length > count) {
    lines.push(DIM(`     … +${rows.length - count} more`));
  }
  const footer = "Type to search · Space ticks · Enter saves · Esc cancels";
  lines.push(
    "",
    ` ${DIM(visibleWidth(footer) < width ? footer : "Space ticks · Enter saves")}`,
  );
  return lines;
}
