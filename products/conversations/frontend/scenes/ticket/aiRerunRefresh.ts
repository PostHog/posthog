import type { AITriage } from '../../types'

export interface AiRerunRefresh {
    /** The triage to show, or null when the fetched one still describes the earlier run. */
    triage: AITriage | null
    finished: boolean
}

/**
 * Decides what a poll after a manual run means. The server records the new run a few seconds after
 * it starts, so until then a fetched "done" with the old finish time belongs to the earlier run.
 */
export function aiRerunRefresh(fetched: unknown, previousFinishedAt: string | null): AiRerunRefresh {
    const triage = (fetched ?? null) as AITriage | null
    if (!triage) {
        return { triage: null, finished: false }
    }
    if (triage.status === 'in_progress') {
        return { triage, finished: false }
    }
    const finished = (triage.finished_at ?? null) !== previousFinishedAt
    return { triage: finished ? triage : null, finished }
}
