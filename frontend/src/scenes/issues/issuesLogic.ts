import { actions, kea, path, reducers, selectors } from 'kea'

import type { issuesSettingsLogicType } from './issuesSettingsLogicType'
import { EventsQuery, NodeKind } from '~/queries/schema'

export const issuesLogic = kea<issuesSettingsLogicType>([
    path(['scenes', 'issues', 'issuesLogic']),
    actions({
        setIssueEvent: (event: string) => ({ event }),
        setQuery: (query: EventsQuery) => ({ query }),
    }),
    reducers({
        issueEvent: [
            '$issue_reported',
            { persist: true },
            {
                setIssueEvent: (_, { event }) => event,
            },
        ],
        providedQuery: [
            null as EventsQuery | null,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    }),
    selectors({
        query: [
            (s) => [s.providedQuery, s.issueEvent],
            (providedQuery, issueEvent) => {
                const q: EventsQuery = providedQuery || {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'person', 'timestamp'],
                    properties: [],
                    event: issueEvent,
                    after: '-24h',
                    limit: 100,
                }
                q.event = issueEvent
                console.log('changing query', { q, providedQuery, issueEvent })
                return q
            },
        ],
    }),
])
