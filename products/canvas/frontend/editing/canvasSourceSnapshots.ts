import type { CanvasCapabilitiesApi, CanvasSourceProjectApi } from '../generated/api.schemas'
import { canvasCapabilities } from './blockLibrary/blockProject'
import type { ParamSchema } from './blockLibrary/params'
import type { GridGrowth, SourceFiles, SourceRange } from './blockLibrary/sourceEdits'

// The local edit state of one canvas. Each
// function returns a new entry, so the kea reducer that holds it stays a thin dispatch.

const HISTORY_LIMIT = 80
const MAX_NOTED_CHANGES = 20

/** What the edit runtime in the frame reports about the element the author selected. */
export interface CanvasEditSelection {
    rev: number
    source: SourceRange | null
    blockType: string | null
    blockId: string | null
    props: Record<string, unknown>
    tag: string
    text: string | null
    layout: {
        inGrid: boolean
        grow: GridGrowth | null
        grid: SourceRange | null
    }
    params: ParamSchema | null
}

export interface CanvasSourceEntry {
    project: CanvasSourceProjectApi
    files: SourceFiles
    savedFiles: SourceFiles
    baseVersionId: string | null
    saving: boolean
    saveError: string | null
    conflict: { versionId: string | null } | null
    past: SourceFiles[]
    future: SourceFiles[]
    /** Bumped on every change to the files, so the frame knows to remount. */
    rev: number
    focusBlockId: string | null
    focusSource: string | null
    rootSource: SourceRange | null
    /** The rev the frame last mounted. Source ranges from an older mount point at stale offsets. */
    mountedRev: number
    changes: string[]
}

export function loadSourceEntry(
    previous: CanvasSourceEntry | null,
    project: CanvasSourceProjectApi,
    versionId: string | null
): CanvasSourceEntry {
    return {
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
    }
}

export function applySourceFiles(
    entry: CanvasSourceEntry,
    files: SourceFiles,
    focusBlockId: string | null = null,
    focusSource: string | null = null
): CanvasSourceEntry {
    return {
        ...entry,
        project: {
            ...entry.project,
            capabilities: canvasCapabilities(entry.project.capabilities, files) as CanvasCapabilitiesApi | undefined,
        },
        files,
        past: [...entry.past, entry.files].slice(-HISTORY_LIMIT),
        future: [],
        rev: entry.rev + 1,
        focusBlockId,
        focusSource,
    }
}

export function undoSourceEntry(entry: CanvasSourceEntry): CanvasSourceEntry {
    const previous = entry.past[entry.past.length - 1]
    if (!previous) {
        return entry
    }
    return {
        ...entry,
        files: previous,
        past: entry.past.slice(0, -1),
        future: [entry.files, ...entry.future],
        rev: entry.rev + 1,
        changes: [...entry.changes, 'Undid a change'],
        focusBlockId: null,
        focusSource: null,
    }
}

export function redoSourceEntry(entry: CanvasSourceEntry): CanvasSourceEntry {
    const [next, ...rest] = entry.future
    if (!next) {
        return entry
    }
    return {
        ...entry,
        files: next,
        past: [...entry.past, entry.files],
        future: rest,
        rev: entry.rev + 1,
        changes: [...entry.changes, 'Redid a change'],
        focusBlockId: null,
        focusSource: null,
    }
}

export function setSourceSaving(
    entry: CanvasSourceEntry,
    saving: boolean,
    error: string | null = null
): CanvasSourceEntry {
    return { ...entry, saving, saveError: error }
}

export function markSourceSaved(
    entry: CanvasSourceEntry,
    files: SourceFiles,
    versionId: string,
    noted: number
): CanvasSourceEntry {
    return {
        ...entry,
        savedFiles: files,
        baseVersionId: versionId,
        saving: false,
        saveError: null,
        changes: entry.changes.slice(noted),
    }
}

export function noteSourceChange(entry: CanvasSourceEntry, label: string): CanvasSourceEntry {
    return {
        ...entry,
        changes:
            entry.changes[entry.changes.length - 1] === label
                ? entry.changes
                : [...entry.changes, label].slice(-MAX_NOTED_CHANGES),
    }
}

export function setSourceConflict(entry: CanvasSourceEntry, versionId: string | null): CanvasSourceEntry {
    return { ...entry, saving: false, saveError: null, conflict: { versionId } }
}

export function resolveSourceConflict(entry: CanvasSourceEntry, keepLocal: boolean): CanvasSourceEntry {
    return keepLocal
        ? { ...entry, baseVersionId: entry.conflict?.versionId ?? entry.baseVersionId, conflict: null }
        : {
              ...entry,
              files: entry.savedFiles,
              past: [],
              future: [],
              rev: entry.rev + 1,
              changes: [],
              conflict: null,
          }
}

export function setSourceMounted(
    entry: CanvasSourceEntry,
    rev: number,
    rootSource: SourceRange | null
): CanvasSourceEntry {
    return { ...entry, mountedRev: rev, rootSource }
}

export function isRootSelection(
    entry: CanvasSourceEntry | null,
    selection: CanvasEditSelection | null | undefined
): boolean {
    const root = entry?.rootSource
    return !!selection?.source && !!root && selection.source.file === root.file && selection.source.start === root.start
}

export function isSourceDirty(entry: CanvasSourceEntry | null | undefined): boolean {
    return !!entry && entry.files !== entry.savedFiles
}

/** Whether a selection or drop target still points at the files on screen. */
export function isFreshRev(entry: CanvasSourceEntry | null, rev: number): boolean {
    return !!entry && entry.mountedRev === entry.rev && rev === entry.rev
}

/** The version-history message for a save, built from the labels of the edits it carries. */
export function describeChanges(changes: string[]): string {
    const unique = Array.from(new Set(changes))
    if (unique.length === 0) {
        return 'Edited the canvas'
    }
    if (unique.length === 1) {
        return unique[0] ?? 'Edited the canvas'
    }
    if (unique.length <= 3) {
        return `${unique.slice(0, -1).join(', ')} and ${unique[unique.length - 1]?.toLowerCase()}`
    }
    return `${unique.slice(0, 2).join(', ')} and ${unique.length - 2} more changes`
}
