import { Button, Card, ScrollArea, Text } from "@posthog/quill";
import * as icons from "lucide-react";
import {
  LIBRARY_PANEL_CLOSE,
  LIBRARY_PANEL_HINT,
  LIBRARY_PANEL_TITLE,
} from "../canvasV2Copy";
import {
  CANVAS_V2_LIBRARY,
  type CanvasV2LibraryEntry,
} from "../library/registry";
import { CANVAS_V2_DRAG_MIME } from "./DropCaptureLayer";

export interface LibraryPaletteProps {
  onAdd: (entry: CanvasV2LibraryEntry) => void;
  onDragStateChange: (dragging: boolean) => void;
  onClose: () => void;
}

/** The ready-made fragments a person can drag or click onto the board. */
export function LibraryPalette({
  onAdd,
  onDragStateChange,
  onClose,
}: LibraryPaletteProps) {
  return (
    <div className="@container flex h-full min-h-0 w-full flex-col overflow-x-hidden border-l">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
        <Text weight="medium">{LIBRARY_PANEL_TITLE}</Text>
        <Button variant="link-muted" size="sm" onClick={onClose}>
          {LIBRARY_PANEL_CLOSE}
        </Button>
      </div>
      <Text size="xs" variant="muted" className="shrink-0 px-3 py-2">
        {LIBRARY_PANEL_HINT}
      </Text>
      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-2 p-3">
          {CANVAS_V2_LIBRARY.map((entry) => (
            <LibraryCard
              key={entry.name}
              entry={entry}
              onAdd={onAdd}
              onDragStateChange={onDragStateChange}
            />
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}

function LibraryCard({
  entry,
  onAdd,
  onDragStateChange,
}: {
  entry: CanvasV2LibraryEntry;
  onAdd: (entry: CanvasV2LibraryEntry) => void;
  onDragStateChange: (dragging: boolean) => void;
}) {
  const Icon = resolveIcon(entry.icon);

  return (
    <Card
      className="cursor-grab p-2"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(CANVAS_V2_DRAG_MIME, entry.name);
        event.dataTransfer.effectAllowed = "copy";
        onDragStateChange(true);
      }}
      onDragEnd={() => onDragStateChange(false)}
      onClick={() => onAdd(entry)}
    >
      <div className="flex items-start gap-2">
        {Icon ? <Icon size={16} className="mt-0.5 shrink-0" /> : null}
        <div className="flex min-w-0 flex-col">
          <Text size="sm" weight="medium">
            {entry.label}
          </Text>
          <Text size="xs" variant="muted">
            {entry.description}
          </Text>
        </div>
      </div>
    </Card>
  );
}

type IconComponent = (props: {
  size?: number;
  className?: string;
}) => JSX.Element;

function resolveIcon(name: string): IconComponent | null {
  const candidate = (icons as unknown as Record<string, unknown>)[name];
  return typeof candidate === "function" ? (candidate as IconComponent) : null;
}
