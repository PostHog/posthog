import { TodayWorkItem } from './todayWorkItems'

export interface TodaySessionDot {
    /** `hollow` is settled, `solid` wants a look, `failed` is red, `spinner` is still starting. */
    mark: 'hollow' | 'solid' | 'failed' | 'spinner'
    /** Barely there, for a run somebody stopped. */
    faint: boolean
    label: string
}

const STARTING_LABELS: Record<string, string> = { not_started: 'Starting', queued: 'Queued' }

/**
 * A session's state as one dot, like the PostHog Desktop task rows. The dot shows attention and activity only,
 * so every settled state shares the same quiet ring.
 */
export function todaySessionDot(
    item: Pick<TodayWorkItem, 'status' | 'runEnvironment'>,
    unread: boolean
): TodaySessionDot {
    const { status } = item
    const startingLabel = status ? STARTING_LABELS[status] : undefined
    if (status === 'failed') {
        return { mark: 'failed', faint: false, label: 'Failed' }
    }
    // A local run can stay `queued` after the agent finishes, so only a cloud run shows the spinner.
    if (startingLabel && item.runEnvironment === 'cloud') {
        return { mark: 'spinner', faint: false, label: startingLabel }
    }
    if (status === 'in_progress') {
        return { mark: 'solid', faint: false, label: 'Running' }
    }
    if (unread) {
        return { mark: 'solid', faint: false, label: 'Unread' }
    }
    if (status === 'cancelled') {
        return { mark: 'hollow', faint: true, label: 'Stopped' }
    }
    return { mark: 'hollow', faint: false, label: status === 'completed' ? 'Completed' : (startingLabel ?? 'Idle') }
}
