import {
  CaretLeft,
  CheckCircle,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import {
  isRootSelection,
  isSourceDirty,
  useCanvasEditSelection,
  useCanvasLibraryOpen,
  useCanvasSourceEntry,
  useCanvasSourceStore,
} from "@posthog/ui/features/canvas/blocks/canvasSourceStore";
import { SourceInspector } from "@posthog/ui/features/canvas/blocks/inspector/SourceInspector";
import {
  LIBRARY,
  LIBRARY_GROUPS,
  type LibraryEntry,
  libraryIcon,
  libraryLabel,
} from "@posthog/ui/features/canvas/blocks/libraryCatalog";
import { beginSourceDrag } from "@posthog/ui/features/canvas/blocks/sourceDrag";
import { useCanvasSourceActions } from "@posthog/ui/features/canvas/blocks/useCanvasSourceActions";
import { SearchInput } from "@posthog/ui/primitives/SearchInput";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { type ReactNode, useMemo, useState } from "react";

interface SaveStatus {
  saving: boolean;
  dirty: boolean;
  error: string | null;
}

function SaveIndicator({ status }: { status: SaveStatus }) {
  if (status.error) {
    return (
      <span className="flex items-center gap-1 text-[11px] text-destructive">
        <WarningCircle size={12} />
        Not saved
      </span>
    );
  }
  if (status.saving || status.dirty) {
    return (
      <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
        <Spinner size="xs" aria-hidden="true" />
        Saving
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
      <CheckCircle size={12} />
      Saved
    </span>
  );
}

function LibraryItem({
  entry,
  onPointerDown,
  onActivate,
}: {
  entry: LibraryEntry;
  onPointerDown: (event: React.PointerEvent, entry: LibraryEntry) => void;
  onActivate: (entry: LibraryEntry) => void;
}) {
  const Icon = entry.icon;
  return (
    <button
      type="button"
      aria-label={`Add ${entry.label}`}
      data-blocks-library-item={entry.type}
      onPointerDown={(event) => onPointerDown(event, entry)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onActivate(entry);
        }
      }}
      className="group/item flex w-full cursor-grab select-none items-center gap-2.5 rounded-md px-2 py-1.5 text-left outline-none transition-[background-color,scale] duration-150 ease-out hover:bg-fill-hover focus-visible:bg-fill-hover active:scale-[0.98] active:cursor-grabbing motion-reduce:active:scale-100"
    >
      <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-[color,border-color] duration-150 group-hover/item:border-accent-8 group-hover/item:text-accent-11">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="truncate font-medium text-foreground text-xs">
          {entry.label}
        </div>
        <div className="line-clamp-2 text-[11px] text-muted-foreground leading-snug">
          {entry.description}
        </div>
      </div>
    </button>
  );
}

function AskAgentCard({
  onAskAgent,
}: {
  onAskAgent: (message: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() =>
        onAskAgent(
          "Improve this canvas. Keep the blocks I placed, and make the layout clear and consistent.",
        )
      }
      className="mx-2 mt-4 flex w-[calc(100%-1rem)] items-start gap-2.5 rounded-md border border-border border-dashed px-2.5 py-2 text-left transition-colors hover:border-accent-8 hover:bg-fill-hover"
    >
      <Sparkle size={14} className="mt-px shrink-0 text-accent-11" />
      <span className="min-w-0">
        <span className="block font-medium text-foreground text-xs">
          Ask the agent
        </span>
        <span className="block text-[11px] text-muted-foreground leading-snug">
          Blocks are code in this canvas. The agent can change them, or build
          what no block covers.
        </span>
      </span>
    </button>
  );
}

function Library({
  addsAfter,
  onPointerDown,
  onActivate,
  onAskAgent,
}: {
  addsAfter: string | null;
  onPointerDown: (event: React.PointerEvent, entry: LibraryEntry) => void;
  onActivate: (entry: LibraryEntry) => void;
  onAskAgent: (message: string) => void;
}) {
  const [search, setSearch] = useState("");
  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const matches = (entry: LibraryEntry) =>
      !needle ||
      entry.label.toLowerCase().includes(needle) ||
      entry.description.toLowerCase().includes(needle);
    return LIBRARY_GROUPS.flatMap((group) => {
      const entries = LIBRARY.filter(
        (entry) => entry.group === group && matches(entry),
      );
      return entries.length > 0 ? [{ group, entries }] : [];
    });
  }, [search]);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-3 pt-3 pb-2">
        <SearchInput
          value={search}
          onValueChange={setSearch}
          placeholder="Search blocks"
          className="w-full"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-4">
        {groups.map(({ group, entries }) => (
          <div key={group} className="mt-2">
            <div className="px-2 pb-1 font-medium text-[10.5px] text-muted-foreground uppercase tracking-wide">
              {group}
            </div>
            {entries.map((entry) => (
              <LibraryItem
                key={entry.type}
                entry={entry}
                onPointerDown={onPointerDown}
                onActivate={onActivate}
              />
            ))}
          </div>
        ))}
        {groups.length === 0 ? (
          <div className="px-3 py-6 text-center text-muted-foreground text-xs">
            No blocks match “{search}”
          </div>
        ) : null}
        <div className="mx-2 mt-4 rounded-md bg-muted/50 px-2.5 py-2 text-[11px] text-muted-foreground leading-snug">
          {addsAfter
            ? `Click a block to add it after the selected ${addsAfter.toLowerCase()}, or drag it anywhere in the canvas.`
            : "Click a block to add it at the end, or drag it anywhere in the canvas."}
        </div>
        <AskAgentCard onAskAgent={onAskAgent} />
      </div>
    </div>
  );
}

const NOTICE_TONES = {
  error: { surface: "bg-destructive/5", icon: "text-destructive" },
  warning: { surface: "bg-muted/40", icon: "text-warning-foreground" },
};

function PanelNotice({
  tone,
  title,
  detail,
  children,
}: {
  tone: keyof typeof NOTICE_TONES;
  title: string;
  detail: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`flex flex-col gap-2 border-border border-b px-3 py-2.5 ${NOTICE_TONES[tone].surface}`}
    >
      <div className="flex items-start gap-2">
        <WarningCircle
          size={14}
          className={`mt-px shrink-0 ${NOTICE_TONES[tone].icon}`}
        />
        <div className="min-w-0 text-[11.5px] leading-snug">
          <div className="font-medium text-foreground">{title}</div>
          <div className="break-words text-muted-foreground">{detail}</div>
        </div>
      </div>
      <div className="flex gap-1.5 pl-5">{children}</div>
    </div>
  );
}

export function CanvasBlocksPanel({
  canvasId,
  onAskAgent,
}: {
  canvasId: string;
  onAskAgent: (message: string) => void;
}) {
  const entry = useCanvasSourceEntry(canvasId);
  const selection = useCanvasEditSelection(canvasId);
  const libraryOpen = useCanvasLibraryOpen(canvasId);
  const actions = useCanvasSourceActions(canvasId);

  if (!entry) {
    return (
      <div className="p-3 text-muted-foreground text-xs">
        Blocks load with the canvas.
      </div>
    );
  }
  const store = useCanvasSourceStore.getState();
  const status: SaveStatus = {
    saving: entry.saving,
    dirty: isSourceDirty(entry),
    error:
      entry.saveError ??
      (entry.conflict ? "This canvas changed somewhere else" : null),
  };
  const isRoot = isRootSelection(entry, selection);
  const SelectedIcon = libraryIcon(selection?.blockType ?? null);
  const inspecting = !!selection && !libraryOpen;
  const addsAfter =
    selection && !isRoot
      ? libraryLabel(selection.blockType, selection.tag)
      : null;

  const addFromLibrary = (blockType: string) => {
    store.setLibraryOpen(canvasId, true);
    actions.addAfterSelection(blockType);
  };

  const onLibraryPointerDown = (
    event: React.PointerEvent,
    item: LibraryEntry,
  ) => {
    if (event.button !== 0) return;
    event.preventDefault();
    beginSourceDrag({
      source: { kind: "new", blockType: item.type },
      startX: event.clientX,
      startY: event.clientY,
      onDrop: (source, hit) => {
        store.setLibraryOpen(canvasId, true);
        actions.drop(source, hit);
      },
      onClick: () => addFromLibrary(item.type),
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1.5 border-border border-b px-3">
        {inspecting ? (
          <Button
            variant="default"
            size="xs"
            onClick={() => store.setLibraryOpen(canvasId, true)}
          >
            <CaretLeft size={11} />
            All blocks
          </Button>
        ) : (
          <span className="font-medium text-[11px] text-muted-foreground">
            Library
          </span>
        )}
        <div className="flex-1" />
        <SaveIndicator status={status} />
      </div>
      {entry.saveError ? (
        <PanelNotice
          tone="error"
          title="Your changes are not saved"
          detail={entry.saveError}
        >
          <Button
            variant="outline"
            size="xs"
            onClick={() => store.setSaving(canvasId, false, null)}
          >
            Try again
          </Button>
          <Button
            variant="default"
            size="xs"
            onClick={() =>
              onAskAgent(
                `Saving this canvas fails with: "${entry.saveError}". Fix the canvas source so it passes validation.`,
              )
            }
          >
            <Sparkle size={11} />
            Ask the agent to fix
          </Button>
        </PanelNotice>
      ) : null}
      {entry.conflict ? (
        <PanelNotice
          tone="warning"
          title="This canvas changed somewhere else"
          detail="A newer version was saved while you edited. Load it and drop your unsaved edits, or keep your edits and replace it."
        >
          <Button
            variant="outline"
            size="xs"
            onClick={() => store.resolveConflict(canvasId, false)}
          >
            Load the latest
          </Button>
          <Button
            variant="default"
            size="xs"
            onClick={() => store.resolveConflict(canvasId, true)}
          >
            Keep my edits
          </Button>
        </PanelNotice>
      ) : null}
      {inspecting && selection ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex items-center gap-2.5 border-border border-b px-3 py-2.5">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-accent-3 text-accent-11">
              <SelectedIcon size={14} />
            </div>
            <div className="min-w-0">
              <div className="font-medium text-foreground text-xs">
                {isRoot
                  ? "Canvas"
                  : libraryLabel(selection.blockType, selection.tag)}
              </div>
              <div className="truncate font-mono text-[10.5px] text-muted-foreground">
                {selection.source?.file ?? ""}
              </div>
            </div>
          </div>
          <SourceInspector
            key={
              selection.blockId ??
              `${selection.source?.file}:${selection.source?.start}`
            }
            selection={selection}
            isRoot={isRoot}
            onProps={(props) => actions.updateProps(selection, props)}
            onText={(text) => actions.setText(selection, text)}
            onDuplicate={() => actions.duplicate(selection)}
            onRemove={() => actions.remove(selection)}
          />
          {isRoot ? null : (
            <div className="px-3 pb-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  onAskAgent(
                    `Change the ${libraryLabel(selection.blockType, selection.tag).toLowerCase()} at ${selection.source?.file ?? "the canvas"}${selection.blockId ? ` (blockId ${selection.blockId})` : ""}: `,
                  )
                }
              >
                <Sparkle size={12} />
                Ask the agent about this
              </Button>
            </div>
          )}
        </div>
      ) : (
        <Library
          addsAfter={addsAfter}
          onPointerDown={onLibraryPointerDown}
          onActivate={(item) => addFromLibrary(item.type)}
          onAskAgent={onAskAgent}
        />
      )}
    </div>
  );
}
