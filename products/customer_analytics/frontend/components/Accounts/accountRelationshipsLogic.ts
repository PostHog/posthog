import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { UserBasicType } from '~/types'

import {
    accountsRelationshipsCreate,
    accountsRelationshipsEndCreate,
    accountsRelationshipsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountRelationshipApi,
    AccountRelationshipDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_HOGQL_DATA_NODE_KEY, ACCOUNTS_METRICS_DATA_NODE_KEY } from '../../constants'
import type { accountRelationshipsLogicType } from './accountRelationshipsLogicType'
import { accountsColumnConfigLogic, ROLE_KEY_BY_NAME } from './accountsColumnConfigLogic'
import { AccountsEvents } from './constants'

export interface AccountRelationshipsLogicProps {
    accountId: string
}

// Assignments also render as list columns.
function refreshAccountsList(): void {
    dataNodeLogic.findMounted({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY })?.actions.loadData('force_async')
    dataNodeLogic.findMounted({ key: ACCOUNTS_METRICS_DATA_NODE_KEY })?.actions.loadData('force_async')
}

export const accountRelationshipsLogic = kea<accountRelationshipsLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountRelationshipsLogic', key]),
    props({} as AccountRelationshipsLogicProps),
    key((props) => props.accountId),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], accountsColumnConfigLogic, ['relationshipDefinitions']],
    })),
    actions({
        assignRelationship: (definition: AccountRelationshipDefinitionApi, user: UserBasicType) => ({
            definition,
            user,
        }),
        endRelationship: (relationship: AccountRelationshipApi) => ({ relationship }),
        setDefinitionFilter: (definitionId: string | null) => ({ definitionId }),
        setAssignDefinitionId: (definitionId: string | null) => ({ definitionId }),
        relationshipSaveStarted: true,
        relationshipSaveFinished: true,
    }),
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
    reducers({
        definitionFilter: [
            null as string | null,
            {
                setDefinitionFilter: (_, { definitionId }) => definitionId,
            },
        ],
        assignDefinitionId: [
            null as string | null,
            {
                setAssignDefinitionId: (_, { definitionId }) => definitionId,
            },
        ],
        relationshipSaving: [
            false,
            {
                relationshipSaveStarted: () => true,
                relationshipSaveFinished: () => false,
            },
        ],
    }),
    selectors({
        activeRelationships: [
            (s) => [s.relationships],
            (relationships): AccountRelationshipApi[] =>
                (relationships ?? []).filter((relationship) => !relationship.ended_at),
        ],
        displayedRelationships: [
            (s) => [s.relationships, s.definitionFilter],
            (relationships, definitionFilter): AccountRelationshipApi[] =>
                (relationships ?? [])
                    .filter((relationship) => !definitionFilter || relationship.definition.id === definitionFilter)
                    .sort(
                        (a, b) =>
                            Number(!!a.ended_at) - Number(!!b.ended_at) || b.started_at.localeCompare(a.started_at)
                    ),
        ],
        assignDefinition: [
            (s) => [s.assignDefinitionId, s.relationshipDefinitions],
            (assignDefinitionId, relationshipDefinitions): AccountRelationshipDefinitionApi | null =>
                relationshipDefinitions.find((definition) => definition.id === assignDefinitionId) ?? null,
        ],
        // Limited to definitions in this account's timeline — any other filter value
        // would just show an empty table.
        definitionFilterOptions: [
            (s) => [s.relationships],
            (relationships): AccountRelationshipDefinitionApi[] => {
                const byId = new Map<string, AccountRelationshipDefinitionApi>()
                for (const relationship of relationships ?? []) {
                    byId.set(relationship.definition.id, relationship.definition)
                }
                return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name))
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        loadRelationshipsFailure: ({ error }) => {
            // No toast: `relationships === null` renders the table's failure empty state.
            posthog.captureException(error, { scope: 'accountRelationshipsLogic.loadRelationships' })
        },
        assignRelationship: async ({ definition, user }) => {
            if (values.relationshipSaving) {
                return
            }
            actions.relationshipSaveStarted()
            try {
                // Assigning a single-holder relationship ends the current holder server-side.
                await accountsRelationshipsCreate(String(values.currentTeamId), props.accountId, {
                    definition: definition.id,
                    user: user.id,
                })
                posthog.capture(AccountsEvents.RoleAssigned, {
                    role: ROLE_KEY_BY_NAME[definition.name] ?? definition.name,
                    is_assigned: true,
                    assigned_user_id: user.id,
                    source: 'relationships_tab',
                })
                actions.setAssignDefinitionId(null)
                actions.loadRelationships()
                refreshAccountsList()
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountRelationshipsLogic.assignRelationship' })
                lemonToast.error(`Failed to assign ${definition.name}`)
            } finally {
                actions.relationshipSaveFinished()
            }
        },
        endRelationship: async ({ relationship }) => {
            if (values.relationshipSaving) {
                return
            }
            actions.relationshipSaveStarted()
            try {
                await accountsRelationshipsEndCreate(String(values.currentTeamId), props.accountId, relationship.id)
                posthog.capture(AccountsEvents.RoleAssigned, {
                    role: ROLE_KEY_BY_NAME[relationship.definition.name] ?? relationship.definition.name,
                    is_assigned: false,
                    assigned_user_id: null,
                    source: 'relationships_tab',
                })
                actions.loadRelationships()
                refreshAccountsList()
            } catch (error) {
                posthog.captureException(error as Error, { scope: 'accountRelationshipsLogic.endRelationship' })
                lemonToast.error(`Failed to end ${relationship.definition.name}`)
            } finally {
                actions.relationshipSaveFinished()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRelationships()
    }),
])
