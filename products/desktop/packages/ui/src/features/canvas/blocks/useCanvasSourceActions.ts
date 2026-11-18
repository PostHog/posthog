import {
  type BlockPropsRecord,
  blockDefinition,
  freshBlockProps,
} from "@posthog/core/canvas/blockLibrary/blockDefinitions";
import { syncBlockLibrary } from "@posthog/core/canvas/blockLibrary/blockLibrarySync";
import {
  blockRanges,
  duplicateRange,
  insertBlock,
  isJsxRange,
  moveRange,
  newBlockId,
  placeableTarget,
  removeRange,
  replaceElementText,
  type SourceDropTarget,
  type SourceFiles,
  type SourceRange,
  updateBlockProps,
} from "@posthog/core/canvas/blockLibrary/sourceEdits";
import {
  type CanvasEditSelection,
  isRootSelection,
  useCanvasSourceStore,
} from "@posthog/ui/features/canvas/blocks/canvasSourceStore";
import { libraryLabel } from "@posthog/ui/features/canvas/blocks/libraryCatalog";
import type {
  SourceDragSource,
  SourceDropHit,
} from "@posthog/ui/features/canvas/blocks/sourceDrag";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useMemo } from "react";

export interface CanvasSourceActions {
  insert: (blockType: string, target: SourceDropTarget) => void;
  addAfterSelection: (blockType: string) => void;
  drop: (source: SourceDragSource, hit: SourceDropHit) => void;
  remove: (selection: CanvasEditSelection) => void;
  duplicate: (selection: CanvasEditSelection) => void;
  updateProps: (
    selection: CanvasEditSelection,
    props: BlockPropsRecord,
  ) => void;
  setText: (selection: CanvasEditSelection, text: string) => void;
  select: (selection: CanvasEditSelection | null) => void;
}

function current(canvasId: string) {
  return useCanvasSourceStore.getState().entries[canvasId];
}

function isFresh(canvasId: string, rev: number): boolean {
  const entry = current(canvasId);
  return !!entry && entry.mountedRev === entry.rev && rev === entry.rev;
}

const SIDE_BY_SIDE_BLOCKS = new Set(["Metric", "TopList", "Funnel"]);

function besideSelection(
  selection: CanvasEditSelection,
  blockType: string,
): SourceDropTarget {
  const source = selection.source as SourceRange;
  const pairs =
    selection.blockType === blockType && SIDE_BY_SIDE_BLOCKS.has(blockType);
  const grid = selection.layout.grid;
  if (!pairs && grid) return { ...grid, place: "after" };
  if (!pairs) return { ...source, place: "after" };
  if (!selection.layout.inGrid) return { ...source, place: "right" };
  const grow = selection.layout.grow;
  return grow
    ? { ...source, place: "after", grow }
    : { ...source, place: "after" };
}

export function useCanvasSourceActions(canvasId: string): CanvasSourceActions {
  const setTab = useCanvasChatPanelStore((state) => state.setTab);
  return useMemo(() => {
    const store = () => useCanvasSourceStore.getState();
    const apply = (
      files: SourceFiles,
      focusBlockId: string | null = null,
      focusSource: string | null = null,
    ) =>
      store().apply(
        canvasId,
        syncBlockLibrary(files),
        focusBlockId,
        focusSource,
      );
    const note = (verb: string, selection: CanvasEditSelection) =>
      store().noteChange(
        canvasId,
        `${verb} ${libraryLabel(selection.blockType, selection.tag).toLowerCase()}`,
      );

    const insert = (blockType: string, target: SourceDropTarget) => {
      const entry = current(canvasId);
      const definition = blockDefinition(blockType);
      if (!entry || !definition) return;
      const blockId = newBlockId();
      const files = insertBlock(
        entry.files,
        target,
        definition,
        freshBlockProps(definition, entry.files),
        blockId,
      );
      if (files === entry.files) return;
      store().noteChange(canvasId, `Added ${definition.label.toLowerCase()}`);
      apply(files, definition.component ? blockId : null);
      if (definition.needsSetup) store().setLibraryOpen(canvasId, false);
      setTab("blocks");
    };

    const addAfterSelection = (blockType: string) => {
      const entry = current(canvasId);
      if (!entry) return;
      const selection = store().selection[canvasId];
      const root = entry.rootSource;
      const group = blockDefinition(blockType)?.group;
      const control =
        group === "Controls" && root
          ? blockRanges(entry.files, root.file, "Controls").at(-1)
          : undefined;
      if (control) {
        insert(blockType, { ...control, place: "after" });
        return;
      }
      const controlSelected =
        !!selection?.blockType &&
        blockDefinition(selection.blockType)?.group === "Controls";
      const besideAllowed = group === "Controls" || !controlSelected;
      if (
        selection?.source &&
        !isRootSelection(entry, selection) &&
        besideAllowed &&
        isFresh(canvasId, selection.rev)
      ) {
        insert(blockType, besideSelection(selection, blockType));
        return;
      }
      const firstData =
        group === "Data" && root
          ? blockRanges(entry.files, root.file, "Data")[0]
          : undefined;
      if (firstData) {
        insert(blockType, { ...firstData, place: "before" });
        return;
      }
      if (!root || entry.mountedRev !== entry.rev) return;
      const inRoot: SourceDropTarget = { ...root, place: "inside" };
      if (placeableTarget(entry, inRoot)) insert(blockType, inRoot);
    };

    const drop = (dragged: SourceDragSource, hit: SourceDropHit) => {
      const entry = current(canvasId);
      if (!entry || !isFresh(canvasId, hit.rev)) return;
      if (!placeableTarget(entry, hit.target)) return;
      if (dragged.kind === "new") {
        insert(dragged.blockType, hit.target);
        return;
      }
      const range = dragged.selection.source;
      if (!range || !isFresh(canvasId, dragged.selection.rev)) return;
      if (!isJsxRange(entry.files, range)) return;
      const files = moveRange(entry.files, range, hit.target);
      if (files !== entry.files) note("Moved", dragged.selection);
      apply(files, dragged.selection.blockId);
    };

    const remove = (selection: CanvasEditSelection) => {
      const entry = current(canvasId);
      if (!entry || !selection.source || !isFresh(canvasId, selection.rev))
        return;
      if (isRootSelection(entry, selection)) return;
      note("Removed", selection);
      apply(removeRange(entry.files, selection.source));
      store().setSelection(canvasId, null);
    };

    const duplicate = (selection: CanvasEditSelection) => {
      const entry = current(canvasId);
      if (!entry || !selection.source || !isFresh(canvasId, selection.rev))
        return;
      const blockId = newBlockId();
      note("Duplicated", selection);
      apply(
        duplicateRange(entry.files, selection.source, blockId),
        selection.blockId ? blockId : null,
      );
    };

    const updateProps = (
      selection: CanvasEditSelection,
      props: BlockPropsRecord,
    ) => {
      const entry = current(canvasId);
      if (
        !entry ||
        !selection.source ||
        !selection.blockType ||
        !isFresh(canvasId, selection.rev)
      )
        return;
      const files = updateBlockProps(
        entry.files,
        selection.source,
        selection.props,
        props,
      );
      if (files === entry.files) return;
      note("Changed", selection);
      apply(
        files,
        selection.blockId,
        selection.blockId
          ? null
          : `${selection.source.file}|${selection.source.start}`,
      );
      store().setSelection(canvasId, { ...selection, props });
    };

    const setText = (selection: CanvasEditSelection, text: string) => {
      const entry = current(canvasId);
      if (!entry || !selection.source || !isFresh(canvasId, selection.rev))
        return;
      const files = replaceElementText(entry.files, selection.source, text);
      if (files === entry.files) return;
      store().noteChange(canvasId, "Edited text");
      apply(
        files,
        selection.blockId,
        `${selection.source.file}|${selection.source.start}`,
      );
    };

    const select = (selection: CanvasEditSelection | null) => {
      store().setSelection(canvasId, selection);
      if (selection) setTab("blocks");
    };

    return {
      insert,
      addAfterSelection,
      drop,
      remove,
      duplicate,
      updateProps,
      setText,
      select,
    };
  }, [canvasId, setTab]);
}
