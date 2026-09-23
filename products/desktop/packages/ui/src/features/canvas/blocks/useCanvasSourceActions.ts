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
    const source = () => useCanvasSourceStore.getState();
    const store = () => ({
      ...source(),
      apply: (
        id: string,
        files: SourceFiles,
        focusBlockId?: string | null,
        focusSource?: string | null,
      ) =>
        source().apply(id, syncBlockLibrary(files), focusBlockId, focusSource),
    });

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
      useCanvasSourceStore
        .getState()
        .noteChange(canvasId, `Added ${definition.label.toLowerCase()}`);
      store().apply(canvasId, files, definition.component ? blockId : null);
      if (definition.needsSetup)
        useCanvasSourceStore.getState().setLibraryOpen(canvasId, false);
      setTab("blocks");
    };

    const addAfterSelection = (blockType: string) => {
      const entry = current(canvasId);
      if (!entry) return;
      const selection = store().selection[canvasId];
      const root = entry.rootSource;
      const rootSelected =
        !!selection?.source &&
        !!root &&
        selection.source.start === root.start &&
        selection.source.file === root.file;
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
        !rootSelected &&
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
      const inRoot: SourceDropTarget | null = root
        ? { ...root, place: "inside" }
        : null;
      if (
        inRoot &&
        entry.mountedRev === entry.rev &&
        placeableTarget(entry, inRoot)
      )
        insert(blockType, inRoot);
    };

    const drop = (source: SourceDragSource, hit: SourceDropHit) => {
      if (!isFresh(canvasId, hit.rev)) return;
      const target = current(canvasId);
      if (!target || !placeableTarget(target, hit.target)) return;
      if (source.kind === "new") {
        insert(source.blockType, hit.target);
        return;
      }
      const entry = current(canvasId);
      const range = source.selection.source;
      if (!entry || !range || !isFresh(canvasId, source.selection.rev)) return;
      if (!isJsxRange(entry.files, range)) return;
      const files = moveRange(entry.files, range, hit.target);
      if (files !== entry.files)
        useCanvasSourceStore
          .getState()
          .noteChange(
            canvasId,
            `Moved ${libraryLabel(source.selection.blockType, source.selection.tag).toLowerCase()}`,
          );
      store().apply(canvasId, files, source.selection.blockId);
    };

    const remove = (selection: CanvasEditSelection) => {
      const entry = current(canvasId);
      if (!entry || !selection.source || !isFresh(canvasId, selection.rev))
        return;
      if (entry.rootSource && selection.source.start === entry.rootSource.start)
        return;
      useCanvasSourceStore
        .getState()
        .noteChange(
          canvasId,
          `Removed ${libraryLabel(selection.blockType, selection.tag).toLowerCase()}`,
        );
      store().apply(canvasId, removeRange(entry.files, selection.source));
      store().setSelection(canvasId, null);
    };

    const duplicate = (selection: CanvasEditSelection) => {
      const entry = current(canvasId);
      if (!entry || !selection.source || !isFresh(canvasId, selection.rev))
        return;
      const blockId = newBlockId();
      useCanvasSourceStore
        .getState()
        .noteChange(
          canvasId,
          `Duplicated ${libraryLabel(selection.blockType, selection.tag).toLowerCase()}`,
        );
      store().apply(
        canvasId,
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
      const focusSource = `${selection.source.file}|${selection.source.start}`;
      useCanvasSourceStore
        .getState()
        .noteChange(
          canvasId,
          `Changed ${libraryLabel(selection.blockType, selection.tag).toLowerCase()}`,
        );
      store().apply(
        canvasId,
        files,
        selection.blockId,
        selection.blockId ? null : focusSource,
      );
      store().setSelection(canvasId, { ...selection, props });
    };

    const setText = (selection: CanvasEditSelection, text: string) => {
      const entry = current(canvasId);
      if (!entry || !selection.source || !isFresh(canvasId, selection.rev))
        return;
      const files = replaceElementText(entry.files, selection.source, text);
      if (files === entry.files) return;
      useCanvasSourceStore.getState().noteChange(canvasId, "Edited text");
      store().apply(
        canvasId,
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
