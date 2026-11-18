import type { Monaco } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'

export type MountedCodeEditor = {
    editor: editor.IStandaloneCodeEditor
    monaco: Monaco
}

/** Told which editor mounted or unmounted, so a listener can check that one editor alone. */
export type MountedCodeEditorListener = (entry: MountedCodeEditor, change: 'mounted' | 'unmounted') => void

const mountedEditors = new Set<MountedCodeEditor>()
const listeners = new Set<MountedCodeEditorListener>()

export function registerMountedCodeEditor(entry: MountedCodeEditor): () => void {
    mountedEditors.add(entry)
    listeners.forEach((listener) => listener(entry, 'mounted'))
    return () => {
        mountedEditors.delete(entry)
        listeners.forEach((listener) => listener(entry, 'unmounted'))
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

export function subscribeToMountedCodeEditors(listener: MountedCodeEditorListener): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
}
