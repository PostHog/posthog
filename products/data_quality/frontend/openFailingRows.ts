import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { apiErrorDetail } from './checksApi'
import type { DataQualityCheckRunApi } from './generated/api.schemas'
import { latestFailingRowsQuery } from './suiteRuns'

/**
 * Send the caller to this check's failing rows in the SQL editor.
 *
 * The rows that failed only exist in the run's compiled query, and runs load lazily, so a caller
 * that has not expanded the check yet passes `fetchRuns` and gets them loaded here.
 */
export async function openFailingRowsInSqlEditor({
    cachedRuns,
    fetchRuns,
    onRunsFetched,
}: {
    cachedRuns: DataQualityCheckRunApi[] | undefined
    fetchRuns: () => Promise<DataQualityCheckRunApi[]>
    onRunsFetched: (runs: DataQualityCheckRunApi[]) => void
}): Promise<void> {
    let runs = cachedRuns
    if (!runs) {
        try {
            runs = await fetchRuns()
            onRunsFetched(runs)
        } catch (error) {
            lemonToast.error(apiErrorDetail(error) ?? 'Could not load the run history. Try again.')
            return
        }
    }
    const query = latestFailingRowsQuery(runs)
    if (!query) {
        lemonToast.info(
            runs.length
                ? 'The query for this check is no longer kept. Run the check to see its failing rows.'
                : "This check hasn't run yet. Run it to see its failing rows."
        )
        return
    }
    router.actions.push(urls.sqlEditor({ query }))
}
