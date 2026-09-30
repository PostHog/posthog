import { TodayWorkItem } from './todayWorkItems'

export type TodaySessionIconKind =
    | 'chat'
    | 'running'
    | 'queued'
    | 'completed'
    | 'failed'
    | 'stopped'
    | 'pinned'
    | 'session'

const TERMINAL: Record<string, TodaySessionIconKind> = {
    completed: 'completed',
    failed: 'failed',
    cancelled: 'stopped',
}

export function todaySessionIcon(item: TodayWorkItem, pinned: boolean): TodaySessionIconKind {
    if (item.kind === 'chat') {
        return 'chat'
    }
    if (item.status === 'in_progress') {
        return 'running'
    }
    if (item.status && TERMINAL[item.status]) {
        return TERMINAL[item.status]
    }
    if (pinned) {
        return 'pinned'
    }
    if (item.status === 'queued' || item.status === 'not_started') {
        return 'queued'
    }
    return 'session'
}
