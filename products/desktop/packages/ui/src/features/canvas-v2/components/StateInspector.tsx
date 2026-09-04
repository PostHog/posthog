import { CheckIcon } from "@phosphor-icons/react";
import { Badge, Text } from "@posthog/quill";
import type { CanvasV2Fragment } from "@posthog/shared";
import { isField, materializeList, materializeText } from "@posthog/shared";
import {
  STATE_EMPTY,
  STATE_PANEL_CLOSE,
  STATE_USED_BY,
  TOOLBAR_STATE,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { BoardPanel } from "@posthog/ui/features/canvas-v2/components/BoardPanel";
import { type ReactElement, useMemo } from "react";

export interface StateInspectorProps {
  state: Record<string, unknown>;
  fragments: readonly CanvasV2Fragment[];
  onClose: () => void;
}

type ValueView =
  | { shape: "phrase"; text: string }
  | { shape: "text"; text: string }
  | { shape: "checklist"; items: { label: string; done: boolean }[] }
  | { shape: "list"; items: string[] }
  | { shape: "json"; text: string };

interface StateEntry {
  key: string;
  title: string;
  kind: string;
  view: ValueView;
  readers: string[];
}

export function StateInspector({
  state,
  fragments,
  onClose,
}: StateInspectorProps): ReactElement {
  const entries = useMemo(
    () =>
      Object.keys(state)
        .sort()
        .map((key) => describeEntry(key, state[key], fragments)),
    [state, fragments],
  );

  return (
    <BoardPanel
      title={TOOLBAR_STATE}
      closeLabel={STATE_PANEL_CLOSE}
      onClose={onClose}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overflow-x-hidden p-3">
        {entries.length === 0 ? (
          <Text size="sm" variant="muted">
            {STATE_EMPTY}
          </Text>
        ) : null}
        {entries.map((entry) => (
          <div
            key={entry.key}
            className="flex min-w-0 flex-col gap-2 rounded-(--radius-3) border border-(--gray-4) bg-(--gray-1) p-3"
          >
            <div className="flex min-w-0 items-center gap-2">
              <span className="min-w-0 truncate font-medium text-[13px]">
                {entry.title}
              </span>
              <Badge variant="default" className="shrink-0 text-[10px]">
                {entry.kind}
              </Badge>
            </div>
            <ValueBody view={entry.view} />
            {entry.readers.length > 0 ? (
              <p className="text-(--gray-10) text-[11px] leading-snug">
                {STATE_USED_BY(entry.readers)}
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </BoardPanel>
  );
}

function ValueBody({ view }: { view: ValueView }): ReactElement {
  if (view.shape === "phrase") {
    return (
      <p className="font-semibold text-[15px] tracking-tight">{view.text}</p>
    );
  }
  if (view.shape === "text") {
    return (
      <p className="line-clamp-5 whitespace-pre-wrap text-(--gray-11) text-[12px] leading-relaxed">
        {view.text || "—"}
      </p>
    );
  }
  if (view.shape === "checklist") {
    return (
      <div className="flex flex-col gap-1">
        {view.items.map((item) => (
          <div key={item.label} className="flex items-start gap-1.5">
            <span
              className={`mt-[3px] flex size-3 shrink-0 items-center justify-center rounded-[3px] ${
                item.done
                  ? "bg-(--accent-9) text-white"
                  : "border border-(--gray-7)"
              }`}
            >
              {item.done ? <CheckIcon size={8} weight="bold" /> : null}
            </span>
            <span
              className={`text-[12px] leading-snug ${
                item.done ? "text-(--gray-10) line-through" : "text-(--gray-12)"
              }`}
            >
              {item.label}
            </span>
          </div>
        ))}
      </div>
    );
  }
  if (view.shape === "list") {
    return (
      <div className="flex flex-col gap-1">
        {view.items.map((item) => (
          <span key={item} className="truncate text-(--gray-11) text-[12px]">
            {item}
          </span>
        ))}
      </div>
    );
  }
  return (
    <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-(--radius-2) bg-(--gray-3) p-2 font-mono text-[11px] leading-relaxed">
      {view.text}
    </pre>
  );
}

const UNIT_WORDS: Record<string, string> = {
  h: "hours",
  d: "days",
  w: "weeks",
  m: "months",
};

function dateRangePhrase(value: Record<string, unknown>): string | null {
  const from = value.date_from;
  if (typeof from !== "string") return null;
  const match = /^-(\d+)([hdwm])$/.exec(from);
  if (!match) return from;
  const unit = UNIT_WORDS[match[2] ?? "d"] ?? "days";
  return `Last ${Number(match[1])} ${unit}`;
}

function describeEntry(
  key: string,
  value: unknown,
  fragments: readonly CanvasV2Fragment[],
): StateEntry {
  const readers = fragments
    .filter((fragment) => fragment.code.includes(key))
    .map((fragment) => fragment.title ?? fragment.id);
  return { key, title: humanizeKey(key), readers, ...classify(value) };
}

function classify(value: unknown): { kind: string; view: ValueView } {
  if (isField(value)) {
    if (value.__field === "text") {
      return {
        kind: "Text",
        view: { shape: "text", text: materializeText(value).text },
      };
    }
    const items = materializeList<unknown>(value).map((item) => item.value);
    const checks = items.filter(isChecklistItem);
    if (checks.length === items.length && items.length > 0) {
      return { kind: "Checklist", view: { shape: "checklist", items: checks } };
    }
    return {
      kind: "List",
      view: { shape: "list", items: items.map((item) => oneLine(item)) },
    };
  }
  if (isRecord(value)) {
    const phrase = dateRangePhrase(value);
    if (phrase)
      return { kind: "Date range", view: { shape: "phrase", text: phrase } };
    return { kind: "Value", view: { shape: "json", text: pretty(value) } };
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return { kind: "Value", view: { shape: "phrase", text: String(value) } };
  }
  if (typeof value === "string") {
    return { kind: "Text", view: { shape: "text", text: value } };
  }
  return { kind: "Value", view: { shape: "json", text: pretty(value) } };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isChecklistItem(value: unknown): value is {
  label: string;
  done: boolean;
} {
  return (
    isRecord(value) &&
    typeof value.label === "string" &&
    typeof value.done === "boolean"
  );
}

function humanizeKey(key: string): string {
  const words = key
    .split(":")
    .map((part) =>
      part
        .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
        .replace(/[-_]+/g, " ")
        .toLowerCase()
        .trim(),
    )
    .filter((part) => part.length > 0);
  const joined = words.join(" · ");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

function oneLine(value: unknown): string {
  if (typeof value === "string") return value;
  return pretty(value).replace(/\s+/g, " ");
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "undefined";
  } catch {
    return "(unserializable)";
  }
}
