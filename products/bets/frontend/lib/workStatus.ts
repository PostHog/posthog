import type { BetsWorkApi } from '../generated/api.schemas'

export type BetWorkMark =
    | 'spinner'
    | 'waiting'
    | 'attention'
    | 'verified'
    | 'failed'
    | 'neutral'
    | 'previous'
    | 'cancelled'

export interface BetWorkStatus {
    label: string
    mark: BetWorkMark
}

const OUTCOME_MARKS: Record<string, BetWorkMark> = {
    lost: 'failed',
    harmed: 'failed',
    flat: 'neutral',
    broken: 'attention',
    dropped: 'cancelled',
}

const OUTCOME_LABELS: Record<string, string> = {
    won: 'Won',
    lost: 'Lost',
    flat: 'No clear effect',
    harmed: 'Guardrail got worse',
    broken: 'Broken test',
    dropped: 'Dropped',
}

function outcomeLabel(item: BetsWorkApi): string {
    return item.result.outcome ? OUTCOME_LABELS[item.result.outcome] : ''
}

export function workStatus(item: BetsWorkApi): BetWorkStatus {
    const running = ['queued', 'in_progress'].includes(item.task_status)
    switch (item.stage) {
        case 'working':
            return { label: running ? 'Working' : 'Starting', mark: running ? 'spinner' : 'waiting' }
        case 'review':
            return { label: 'In review', mark: 'attention' }
        case 'live':
            return { label: 'Live', mark: 'spinner' }
        case 'done':
            return {
                label:
                    item.kind === 'tracking'
                        ? 'Checked'
                        : item.kind === 'cleanup'
                          ? 'Flag removed'
                          : outcomeLabel(item) || 'Learned',
                mark: (item.kind === 'idea' && OUTCOME_MARKS[item.result.outcome ?? '']) || 'verified',
            }
        case 'dropped':
            return { label: 'Dropped', mark: 'cancelled' }
        default:
            return { label: 'Needs attention', mark: 'attention' }
    }
}

export function liveFact(note: string): string {
    const run = note.match(/Running for (\d+) of (\d+) hours/)
    return run ? `${run[1]} of ${run[2]} hours` : note.replace(/\.$/, '')
}

export function isOpen(item: BetsWorkApi): boolean {
    return ['working', 'review', 'live', 'stuck'].includes(item.stage)
}
