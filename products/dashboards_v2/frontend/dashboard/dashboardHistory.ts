import { objectsEqual } from 'lib/utils/objects'

import type { Dashboard } from './dashboardTypes'

/** Undo and redo for a dashboard. A host keeps one of these, so every host gets the same undo behavior. */
export interface DashboardHistory {
    past: Dashboard[]
    present: Dashboard
    future: Dashboard[]
}

const HISTORY_LIMIT = 100

export function startHistory(dashboard: Dashboard): DashboardHistory {
    return { past: [], present: dashboard, future: [] }
}

/** Adds an edited dashboard as a new undo step. An edit that changed nothing adds no step and keeps what could be redone. */
export function recordEdit(history: DashboardHistory, next: Dashboard): DashboardHistory {
    if (next === history.present || objectsEqual(next, history.present)) {
        return history
    }
    return { past: [...history.past, history.present].slice(-HISTORY_LIMIT), present: next, future: [] }
}

export function undoEdit(history: DashboardHistory): DashboardHistory {
    if (history.past.length === 0) {
        return history
    }
    return {
        past: history.past.slice(0, -1),
        present: history.past[history.past.length - 1],
        future: [history.present, ...history.future],
    }
}

export function redoEdit(history: DashboardHistory): DashboardHistory {
    if (history.future.length === 0) {
        return history
    }
    return {
        past: [...history.past, history.present],
        present: history.future[0],
        future: history.future.slice(1),
    }
}
