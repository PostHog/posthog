import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { readStoredDraftInsightQuery } from './draftInsight'

export function ReloadInsight(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { reportInsightDraftRestored } = useActions(eventUsageLogic)
    const draftQuery = readStoredDraftInsightQuery(currentTeamId)

    if (!draftQuery?.query) {
        return <> </>
    }
    const draftTimestamp = draftQuery.timestamp
    return (
        <div className="text-secondary">
            You have an unsaved insight from {new Date(draftTimestamp).toLocaleString()}.{' '}
            <Link
                to={urls.insightNew({ query: draftQuery.query })}
                onClick={() =>
                    reportInsightDraftRestored(
                        'insight_editor',
                        Math.max(0, Math.round((Date.now() - draftTimestamp) / 1000))
                    )
                }
            >
                Click here
            </Link>{' '}
            to view it.
        </div>
    )
}
