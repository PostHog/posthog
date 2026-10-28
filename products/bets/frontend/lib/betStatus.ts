import type { TodaySessionDot } from '~/layout/today/todaySessionDot'

import type { BetsEntryApi } from '../generated/api.schemas'

export const BET_STATUS_LABELS: Record<BetsEntryApi['status'], string> = {
    setting_up: 'Setting up',
    running: 'Running',
    paused: 'Paused',
    reached: 'Goal reached',
    spent: 'Budget used',
    closed: 'Closed',
}

export const BET_STATUS_BADGES: Record<
    BetsEntryApi['status'],
    'default' | 'success' | 'warning' | 'completed' | 'destructive'
> = {
    setting_up: 'default',
    running: 'success',
    paused: 'warning',
    reached: 'completed',
    spent: 'warning',
    closed: 'default',
}

export function betGlyph(bet: Pick<BetsEntryApi, 'status' | 'needs_you'>): TodaySessionDot {
    if (bet.needs_you) {
        return { mark: 'solid', faint: false, label: 'Needs you' }
    }
    switch (bet.status) {
        case 'setting_up':
        case 'running':
            return { mark: 'spinner', faint: false, label: BET_STATUS_LABELS[bet.status] }
        case 'reached':
            return { mark: 'hollow', faint: false, label: BET_STATUS_LABELS.reached }
        default:
            return { mark: 'hollow', faint: true, label: BET_STATUS_LABELS[bet.status] }
    }
}
