import { actions, kea, path, reducers, selectors } from 'kea'

import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema'

import type { issuesLogicType } from './issuesLogicType'

export const issuesLogic = kea<issuesLogicType>([
    path(['scenes', 'issues', 'issuesLogic']),
    actions({
        setIssueEvent: (event: string) => ({ event }),
        setQuery: (query: EventsQuery) => ({ query }),
    }),
    reducers({
        issueEvent: [
            '$bug_report',
            { persist: true },
            {
                setIssueEvent: (_, { event }) => (event.trim().length > 0 ? event : '$bug_report'),
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
                return q
            },
        ],
        tableQuery: [
            (s) => [s.query],
            (query) => {
                return {
                    kind: NodeKind.DataTableNode,
                    full: false,
                    showOpenEditorButton: false,
                    source: { ...query },
                } as DataTableNode
            },
        ],
    }),
])
