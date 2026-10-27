import type { BetsEntryApi } from '../generated/api.schemas'

export const BET_STATUS_LABELS: Record<BetsEntryApi['status'], string> = {
    setting_up: 'Setting up',
    running: 'Running',
    paused: 'Paused',
    reached: 'Goal reached',
    spent: 'Budget used',
    closed: 'Closed',
}
