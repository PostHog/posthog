import { useSyncExternalStore } from 'react'

import type { Display } from '../spec'

export type EditorPref = 'auto' | 'simple' | 'advanced'
export const EDITOR_PREFS: [EditorPref, string][] = [
    ['auto', 'By dashboard'],
    ['simple', 'Simple'],
    ['advanced', 'Advanced'],
]

const KEY = 'dashboards-v2.editor'
const listeners = new Set<() => void>()
const read = (): EditorPref => {
    try {
        const stored = localStorage.getItem(KEY)
        return stored === 'simple' || stored === 'advanced' ? stored : 'auto'
    } catch {
        return 'auto'
    }
}
export const setEditorPref = (pref: EditorPref): void => {
    try {
        if (pref === 'auto') {
            localStorage.removeItem(KEY)
        } else {
            localStorage.setItem(KEY, pref)
        }
    } catch {}
    listeners.forEach((listener) => listener())
}
export function useEditorPref(): EditorPref {
    return useSyncExternalStore(
        (listener) => {
            listeners.add(listener)
            return () => listeners.delete(listener)
        },
        read,
        () => 'auto' as EditorPref
    )
}
export const editorFor = (pref: EditorPref, display: Display): 'simple' | 'advanced' =>
    pref === 'auto' ? (display === 'spacious' ? 'simple' : 'advanced') : pref
