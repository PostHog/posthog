import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { parseDraftQueryFromLocalStorage } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Node } from '~/queries/schema/schema-general'

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
        <div className="text-secondary mb-4">
            You have an unsaved insight from {new Date(draftQuery.timestamp).toLocaleString()}.{' '}
            <Link to={urls.insightNew({ query: draftQuery.query })}>Click here</Link> to view it.
        </div>
    )
}
