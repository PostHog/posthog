import type { Monaco } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'

export type MountedCodeEditor = {
    editor: editor.IStandaloneCodeEditor
    monaco: Monaco
}

const mountedEditors = new Set<MountedCodeEditor>()
const listeners = new Set<() => void>()

/** Tracks a mounted editor until the returned callback runs. */
export function registerMountedCodeEditor(entry: MountedCodeEditor): () => void {
    mountedEditors.add(entry)
    listeners.forEach((listener) => listener())
    return () => {
        mountedEditors.delete(entry)
        listeners.forEach((listener) => listener())
    }
}

/**
 * The editor rendered inside `container`. A host that only owns the DOM around an editor (a notebook
 * cell) reaches it this way, without importing Monaco or threading a ref through every component.
 */
export function findMountedCodeEditorWithin(container: Element | null): MountedCodeEditor | null {
    if (!container) {
        return null
    }
    for (const entry of mountedEditors) {
        if (container.contains(entry.editor.getContainerDomNode())) {
            return entry
        }
    }
    return null
}

export function subscribeToMountedCodeEditors(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
}
