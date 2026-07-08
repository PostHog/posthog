import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { accountsRelationshipsList } from 'products/customer_analytics/frontend/generated/api'
import type { AccountRelationshipApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountRelationshipsLogicType } from './accountRelationshipsLogicType'

export interface AccountRelationshipsLogicProps {
    accountId: string
}

export const accountRelationshipsLogic = kea<accountRelationshipsLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountRelationshipsLogic', key]),
    props({} as AccountRelationshipsLogicProps),
    key((props) => props.accountId),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ props, values }) => ({
        relationships: [
            null as AccountRelationshipApi[] | null,
            {
                // One fetch serves both surfaces: active rows feed the sidebar summary,
                // the full timeline feeds the history tab.
                loadRelationships: async (): Promise<AccountRelationshipApi[]> =>
                    accountsRelationshipsList(String(values.currentTeamId), props.accountId, {
                        include_history: true,
                    }),
            },
        ],
    })),
    selectors({
        activeRelationships: [
            (s) => [s.relationships],
            (relationships): AccountRelationshipApi[] =>
                (relationships ?? []).filter((relationship) => !relationship.ended_at),
        ],
    }),
    listeners(() => ({
        loadRelationshipsFailure: ({ error }) => {
            // No toast: `relationships === null` renders the table's failure empty state.
            posthog.captureException(error, { scope: 'accountRelationshipsLogic.loadRelationships' })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRelationships()
    }),
])
