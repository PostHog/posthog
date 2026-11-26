import { useCallback, useState } from 'react'

import { type DashboardHistory, recordEdit, redoEdit, startHistory, undoEdit } from './dashboardHistory'
import type { Dashboard } from './dashboardTypes'

/** Undo history for a host that keeps its dashboard in React state rather than in a kea logic. */
export function useDashboardHistory(initial: Dashboard): {
    dashboard: Dashboard
    record: (next: Dashboard) => void
    undo: () => void
    redo: () => void
    canUndo: boolean
    canRedo: boolean
} {
    const [history, setHistory] = useState<DashboardHistory>(() => startHistory(initial))
    const record = useCallback((next: Dashboard) => setHistory((current) => recordEdit(current, next)), [])
    const undo = useCallback(() => setHistory(undoEdit), [])
    const redo = useCallback(() => setHistory(redoEdit), [])
    return {
        dashboard: history.present,
        record,
        undo,
        redo,
        canUndo: history.past.length > 0,
        canRedo: history.future.length > 0,
    }
}
