import type { AITriage } from '../../types'

export interface AiRerunRefresh {
    triage: AITriage | null
    finished: boolean
}

// The server records a new run a few seconds after it starts. Until then a fetched "done" belongs to the earlier run.
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
