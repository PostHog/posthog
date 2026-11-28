import type { BreakPointFunction } from 'kea'

import { aiObservabilityOfflineExperimentsScorerSummariesList } from '../generated/api'
import type { OfflineSummaryPageApi } from '../generated/api.schemas'

export async function readOfflineSummaryPages(
    teamId: number,
    experimentId: string,
    breakpoint: BreakPointFunction,
    onPage: (page: OfflineSummaryPageApi) => void
): Promise<number> {
    let cursor: string | undefined
    let count = 0
    try {
        do {
            const page = await aiObservabilityOfflineExperimentsScorerSummariesList(String(teamId), experimentId, {
                limit: 100,
                cursor,
            })
            breakpoint()
            onPage(page)
            count = page.count
            cursor = page.next_cursor || undefined
        } while (cursor)
    } catch (error) {
        breakpoint()
        throw error
    }
    return count
}
