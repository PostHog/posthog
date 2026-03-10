import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import type { personsSceneLogicType } from './personsSceneLogicType'

export const PEOPLE_LIST_CONTEXT_KEY = 'people-list'

function buildDefaultQuery(personLastSeenAtEnabled: boolean): DataTableNode {
    const columns = [...defaultDataTableColumns(NodeKind.ActorsQuery, personLastSeenAtEnabled), 'person.$delete']
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ActorsQuery,
            tags: { productKey: ProductKey.CUSTOMER_ANALYTICS },
            select: columns,
        },
        defaultColumns: columns,
        full: true,
        propertiesViaUrl: true,
        contextKey: PEOPLE_LIST_CONTEXT_KEY,
    } as DataTableNode
}

export const PEOPLE_LIST_DEFAULT_QUERY = buildDefaultQuery(false)

export const personsSceneLogic = kea<personsSceneLogicType>([
    path(['scenes', 'persons', 'personsSceneLogic']),
    tabAwareScene(),

    connect({ values: [teamLogic, ['currentTeam']] }),

    actions({
        setQuery: (query: DataTableNode) => ({ query }),
        resetDeletedDistinctId: (distinct_id: string) => ({ distinct_id }),
        setShowDisplayNameNudge: (showDisplayNameNudge: boolean) => ({ showDisplayNameNudge }),
        setIsBannerLoading: (isBannerLoading: boolean) => ({ isBannerLoading }),
    }),

    reducers({
        query: [
            PEOPLE_LIST_DEFAULT_QUERY,
            {
                setQuery: (state, { query }) => ({
                    ...query,
                    defaultColumns: query.defaultColumns ?? state.defaultColumns,
                }),
            },
        ],
        showDisplayNameNudge: [
            false,
            {
                setShowDisplayNameNudge: (_, { showDisplayNameNudge }) => showDisplayNameNudge,
            },
        ],
        isBannerLoading: [
            false,
            {
                setIsBannerLoading: (_, { isBannerLoading }) => isBannerLoading,
            },
        ],
    }),

    listeners({
        resetDeletedDistinctId: async ({ distinct_id }) => {
            await api.persons.resetPersonDistinctId(distinct_id)
            lemonToast.success('Distinct ID reset. It may take a few minutes to process.')
        },
    }),

    selectors({
        defaultQuery: [
            (s) => [s.currentTeam],
            (currentTeam): DataTableNode =>
                buildDefaultQuery(currentTeam?.extra_settings?.person_last_seen_at_enabled === true),
        ],
        defaultColumns: [(s) => [s.defaultQuery], (defaultQuery): string[] => defaultQuery.defaultColumns ?? []],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'persons',
                    name: sceneConfigurations[Scene.Persons].name,
                    iconType: sceneConfigurations[Scene.Persons].iconType || 'default_icon_type',
                },
            ],
        ],
    }),

    tabAwareActionToUrl(({ values }) => ({
        setQuery: () => [
            urls.persons(),
            {},
            equal(values.query, values.defaultQuery) ? {} : { q: values.query },
            { replace: true },
        ],
    })),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.persons()]: (_, __, { q: queryParam }): void => {
            if (!equal(queryParam, values.query)) {
                if (!queryParam) {
                    actions.setQuery({
                        ...values.defaultQuery,
                        defaultColumns: values.defaultColumns,
                    })
                } else {
                    if (typeof queryParam === 'object') {
                        actions.setQuery({
                            ...queryParam,
                            defaultColumns: values.defaultColumns,
                        })
                    } else {
                        lemonToast.error('Invalid query in URL')
                        console.error({ queryParam })
                    }
                }
            }
        },
    })),
])
