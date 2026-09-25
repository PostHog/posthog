import type { ParamSchema } from "@posthog/core/canvas/blockLibrary/params";
import type {
  GridGrowth,
  SourceFiles,
  SourceRange,
} from "@posthog/core/canvas/blockLibrary/sourceEdits";
import type { CanvasSourceProject } from "@posthog/core/canvas/dashboardSchemas";
import { create } from "zustand";

const HISTORY_LIMIT = 80;
const MAX_NOTED_CHANGES = 20;

export interface CanvasEditSelection {
  rev: number;
  source: SourceRange | null;
  blockType: string | null;
  blockId: string | null;
  props: Record<string, unknown>;
  tag: string;
  text: string | null;
  layout: {
    inGrid: boolean;
    grow: GridGrowth | null;
    grid: SourceRange | null;
  };
  params: ParamSchema | null;
}

export interface CanvasSourceEntry {
  project: CanvasSourceProject;
  files: SourceFiles;
  savedFiles: SourceFiles;
  baseVersionId: string | null;
  saving: boolean;
  saveError: string | null;
  conflict: { versionId: string | null } | null;
  past: SourceFiles[];
  future: SourceFiles[];
  rev: number;
  focusBlockId: string | null;
  focusSource: string | null;
  rootSource: SourceRange | null;
  mountedRev: number;
  changes: string[];
}

interface CanvasSourceState {
  entries: Record<string, CanvasSourceEntry>;
  selection: Record<string, CanvasEditSelection | null>;
  libraryOpen: Record<string, boolean>;
  setLibraryOpen: (canvasId: string, open: boolean) => void;
  load: (
    canvasId: string,
    project: CanvasSourceProject,
    versionId: string | null,
  ) => void;
  apply: (
    canvasId: string,
    files: SourceFiles,
    focusBlockId?: string | null,
    focusSource?: string | null,
  ) => void;
  undo: (canvasId: string) => void;
  redo: (canvasId: string) => void;
  setSaving: (canvasId: string, saving: boolean, error?: string | null) => void;
  markSaved: (
    canvasId: string,
    files: SourceFiles,
    versionId: string,
    noted: number,
  ) => void;
  noteChange: (canvasId: string, label: string) => void;
  setConflict: (canvasId: string, versionId: string | null) => void;
  resolveConflict: (canvasId: string, keepLocal: boolean) => void;
  setSelection: (
    canvasId: string,
    selection: CanvasEditSelection | null,
  ) => void;
  setMounted: (
    canvasId: string,
    rev: number,
    rootSource: SourceRange | null,
  ) => void;
}

function patch(
  state: CanvasSourceState,
  canvasId: string,
  update: (entry: CanvasSourceEntry) => Partial<CanvasSourceEntry>,
): Partial<CanvasSourceState> {
  const entry = state.entries[canvasId];
  if (!entry) return {};
  return {
    entries: { ...state.entries, [canvasId]: { ...entry, ...update(entry) } },
  };
}

export const useCanvasSourceStore = create<CanvasSourceState>((set) => ({
  entries: {},
  selection: {},
  libraryOpen: {},
  load: (canvasId, project, versionId) =>
    set((state) => {
      const previous = state.entries[canvasId];
      return {
        entries: {
          ...state.entries,
          [canvasId]: {
            project,
            files: project.files,
            savedFiles: project.files,
            baseVersionId: versionId,
            saving: false,
            saveError: null,
            conflict: null,
            past: [],
            future: [],
            rev: (previous?.rev ?? 0) + 1,
            focusBlockId: null,
            focusSource: null,
            rootSource: previous?.rootSource ?? null,
            mountedRev: previous?.mountedRev ?? 0,
            changes: [],
          },
        },
      };
    }),
  apply: (canvasId, files, focusBlockId = null, focusSource = null) =>
    set((state) =>
      patch(state, canvasId, (entry) => ({
        files,
        past: [...entry.past, entry.files].slice(-HISTORY_LIMIT),
        future: [],
        rev: entry.rev + 1,
        focusBlockId,
        focusSource,
      })),
    ),
  undo: (canvasId) =>
    set((state) =>
      patch(state, canvasId, (entry) => {
        const previous = entry.past[entry.past.length - 1];
        if (!previous) return {};
        return {
          files: previous,
          past: entry.past.slice(0, -1),
          future: [entry.files, ...entry.future],
          rev: entry.rev + 1,
          changes: [...entry.changes, "Undid a change"],
          focusBlockId: null,
          focusSource: null,
        };
      }),
    ),
  redo: (canvasId) =>
    set((state) =>
      patch(state, canvasId, (entry) => {
        const [next, ...rest] = entry.future;
        if (!next) return {};
        return {
          files: next,
          past: [...entry.past, entry.files],
          future: rest,
          rev: entry.rev + 1,
          changes: [...entry.changes, "Redid a change"],
          focusBlockId: null,
          focusSource: null,
        };
      }),
    ),
  setSaving: (canvasId, saving, error = null) =>
    set((state) =>
      patch(state, canvasId, () => ({ saving, saveError: error })),
    ),
  markSaved: (canvasId, files, versionId, noted) =>
    set((state) =>
      patch(state, canvasId, (entry) => ({
        savedFiles: files,
        baseVersionId: versionId,
        saving: false,
        saveError: null,
        changes: entry.changes.slice(noted),
      })),
    ),
  noteChange: (canvasId, label) =>
    set((state) =>
      patch(state, canvasId, (entry) => ({
        changes:
          entry.changes[entry.changes.length - 1] === label
            ? entry.changes
            : [...entry.changes, label].slice(-MAX_NOTED_CHANGES),
      })),
    ),
  setConflict: (canvasId, versionId) =>
    set((state) =>
      patch(state, canvasId, () => ({
        saving: false,
        saveError: null,
        conflict: { versionId },
      })),
    ),
  resolveConflict: (canvasId, keepLocal) =>
    set((state) =>
      patch(state, canvasId, (entry) =>
        keepLocal
          ? {
              baseVersionId: entry.conflict?.versionId ?? entry.baseVersionId,
              conflict: null,
            }
          : {
              files: entry.savedFiles,
              past: [],
              future: [],
              rev: entry.rev + 1,
              changes: [],
              conflict: null,
            },
      ),
    ),
  setLibraryOpen: (canvasId, open) =>
    set((state) => ({
      libraryOpen: { ...state.libraryOpen, [canvasId]: open },
    })),
  setSelection: (canvasId, selection) =>
    set((state) => ({
      selection: { ...state.selection, [canvasId]: selection },
    })),
  setMounted: (canvasId, rev, rootSource) =>
    set((state) =>
      patch(state, canvasId, () => ({ mountedRev: rev, rootSource })),
    ),
}));

export function isRootSelection(
  entry: CanvasSourceEntry,
  selection: CanvasEditSelection | null | undefined,
): boolean {
  const root = entry.rootSource;
  return (
    !!selection?.source &&
    !!root &&
    selection.source.file === root.file &&
    selection.source.start === root.start
  );
}

export function isSourceDirty(entry: CanvasSourceEntry | undefined): boolean {
  return !!entry && entry.files !== entry.savedFiles;
}

export function useCanvasSourceEntry(
  canvasId: string,
): CanvasSourceEntry | undefined {
  return useCanvasSourceStore((state) => state.entries[canvasId]);
}

export function useCanvasLibraryOpen(canvasId: string): boolean {
  return useCanvasSourceStore((state) => state.libraryOpen[canvasId] ?? false);
}

export function useCanvasEditSelection(
  canvasId: string,
): CanvasEditSelection | null {
  return useCanvasSourceStore((state) => state.selection[canvasId] ?? null);
}

export function describeChanges(changes: string[]): string {
  const unique = Array.from(new Set(changes));
  if (unique.length === 0) return "Edited the canvas";
  if (unique.length === 1) return unique[0] ?? "Edited the canvas";
  if (unique.length <= 3) {
    return `${unique.slice(0, -1).join(", ")} and ${unique[unique.length - 1]?.toLowerCase()}`;
  }
  return `${unique.slice(0, 2).join(", ")} and ${unique.length - 2} more changes`;
}
