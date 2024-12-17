import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { parseDraftQueryFromLocalStorage } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema'

export function ReloadInsight(): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const draftQueryLocalStorage = localStorage.getItem(`draft-query-${currentTeamId}`)
    let draftQuery: { query: Node<Record<string, any>>; timestamp: number } | null = null
    if (draftQueryLocalStorage) {
        const parsedQuery = parseDraftQueryFromLocalStorage(draftQueryLocalStorage)
        if (parsedQuery) {
            draftQuery = parsedQuery
        } else {
            localStorage.removeItem(`draft-query-${currentTeamId}`)
        }
    }

    if (!draftQuery?.query) {
        return <> </>
    }
    return (
        <div className="text-muted-alt mb-4">
            You have an unsaved insight from {new Date(draftQuery.timestamp).toLocaleString()}.{' '}
            <Link to={urls.insightNew(undefined, null, draftQuery.query)}>Click here</Link> to view it.
        </div>
    )
}
