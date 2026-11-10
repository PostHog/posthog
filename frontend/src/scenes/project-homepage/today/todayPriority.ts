import type { TodayRowTone } from './TodayRow'

export function priorityTone(priority: string | null | undefined): TodayRowTone {
    if (priority === 'P0' || priority === 'P1') {
        return 'risk'
    }
    return priority === 'P2' ? 'neutral' : 'quiet'
}
