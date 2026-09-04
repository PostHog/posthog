import { ScrollArea, Text } from "@posthog/quill";
import { libraryEntryIcon } from "@posthog/ui/features/canvas-v2/library/entryIcon";
import {
  LIBRARY_GROUP_DATA,
  LIBRARY_GROUP_FRAMES,
  LIBRARY_GROUP_NOTES,
  LIBRARY_PANEL_CLOSE,
  LIBRARY_PANEL_HINT,
  LIBRARY_PANEL_TITLE,
} from "../canvasV2Copy";
import {
  CANVAS_V2_LIBRARY,
  type CanvasV2LibraryEntry,
  type CanvasV2LibraryGroup,
} from "../library/registry";
import { BoardPanel } from "./BoardPanel";
import { CANVAS_V2_DRAG_MIME } from "./DropCaptureLayer";

const GROUPS: { group: CanvasV2LibraryGroup; title: string }[] = [
  { group: "notes", title: LIBRARY_GROUP_NOTES },
  { group: "data", title: LIBRARY_GROUP_DATA },
  { group: "frames", title: LIBRARY_GROUP_FRAMES },
];

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
    <BoardPanel
      title={LIBRARY_PANEL_TITLE}
      closeLabel={LIBRARY_PANEL_CLOSE}
      onClose={onClose}
    >
      <ScrollArea className="min-h-0 flex-1">
        <Text size="xs" variant="muted" className="block px-3 pt-3 pb-1">
          {LIBRARY_PANEL_HINT}
        </Text>
        {GROUPS.map(({ group, title }) => (
          <div className="flex flex-col gap-px p-2 pt-1" key={group}>
            <Text
              size="xs"
              variant="muted"
              className="block px-2 pt-2 pb-1 font-medium"
            >
              {title}
            </Text>
            {CANVAS_V2_LIBRARY.filter((entry) => entry.group === group).map(
              (entry) => (
                <LibraryRow
                  key={entry.name}
                  entry={entry}
                  onAdd={onAdd}
                  onDragStateChange={onDragStateChange}
                />
              ),
            )}
          </div>
        ))}
      </ScrollArea>
    </BoardPanel>
  );
}

function LibraryRow({
  entry,
  onAdd,
  onDragStateChange,
}: {
  entry: CanvasV2LibraryEntry;
  onAdd: (entry: CanvasV2LibraryEntry) => void;
  onDragStateChange: (dragging: boolean) => void;
}) {
  const Icon = libraryEntryIcon(entry.name);

  return (
    <button
      type="button"
      title={entry.description}
      draggable
      className="flex w-full cursor-grab items-start gap-2.5 rounded-(--radius-2) px-2 py-2 text-left transition-colors hover:bg-(--gray-3) active:cursor-grabbing"
      onDragStart={(event) => {
        event.dataTransfer.setData(CANVAS_V2_DRAG_MIME, entry.name);
        event.dataTransfer.effectAllowed = "copy";
        onDragStateChange(true);
      }}
      onDragEnd={() => onDragStateChange(false)}
      onClick={() => onAdd(entry)}
    >
      <span className="mt-px flex size-7 shrink-0 items-center justify-center rounded-(--radius-2) bg-(--accent-a3) text-(--accent-11)">
        <Icon size={15} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-medium text-[13px] leading-tight">
          {entry.label}
        </span>
        <span className="line-clamp-2 text-(--gray-11) text-[11px] leading-[1.35]">
          {entry.description}
        </span>
      </span>
    </button>
  );
}
