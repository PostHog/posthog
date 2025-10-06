import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'

import { isSessionPropertyFilters } from '~/queries/schema-guards'
import {
    DataTableNode,
    DateRange,
    NodeKind,
    SessionAttributionExplorerQuery,
    SessionAttributionGroupBy,
} from '~/queries/schema/schema-general'
import { Breadcrumb, SessionPropertyFilter } from '~/types'

import type { sessionAttributionExplorerLogicType } from './sessionAttributionExplorerLogicType'

export const initialProperties = [] as SessionPropertyFilter[]
export const initialGroupBy = [
    SessionAttributionGroupBy.Source,
    SessionAttributionGroupBy.Medium,
    SessionAttributionGroupBy.ChannelType,
    SessionAttributionGroupBy.ReferringDomain,
]
export const defaultDateRange: DateRange = { date_from: '-7d', date_to: 'now' }
export const sessionAttributionExplorerLogic = kea<sessionAttributionExplorerLogicType>([
    path(['scenes', 'webAnalytics', 'sessionDebuggerLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setProperties: (properties: SessionPropertyFilter[]) => ({ properties }),
        setDateRange: (dateRange: DateRange | null) => ({ dateRange }),
        setStateFromUrl: (state: { properties: SessionPropertyFilter[]; dateRange: DateRange | null }) => ({
            state,
        }),
        enableGroupBy: (groupBy: SessionAttributionGroupBy) => {
            return { groupBy }
        },
        disableGroupBy: (groupBy: SessionAttributionGroupBy) => {
            return { groupBy }
        },
    }),
    reducers({
        properties: [
            initialProperties,
            {
                setProperties: (_, { properties }) => properties,
                setStateFromUrl: (_, { state }) => state.properties,
            },
        ],
        dateRange: [
            null as DateRange | null,
            {
                setDateRange: (_, { dateRange }) => dateRange,
                setStateFromUrl: (_, { state }) => state.dateRange,
            },
        ],
        groupBy: [
            initialGroupBy,
            {
                enableGroupBy: (state, { groupBy }) => {
                    return Array.from(new Set([...state, groupBy]))
                },
                disableGroupBy: (state, { groupBy }) => {
                    return state.filter((item) => item !== groupBy)
                },
            },
        ],
    }),
    selectors({
        query: [
            (s) => [s.properties, s.dateRange, s.groupBy],
            (properties: SessionPropertyFilter[], dateRange, groupBy): DataTableNode => {
                const filters = {
                    properties,
                    dateRange: dateRange ?? defaultDateRange,
                }
                const source: SessionAttributionExplorerQuery = {
                    kind: NodeKind.SessionAttributionExplorerQuery,
                    groupBy: groupBy,
                    filters: filters,
                    tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: source,
                    showPropertyFilter: [TaxonomicFilterGroupType.SessionProperties],
                    showDateRange: true,
                    showOpenEditorButton: true,
                    showReload: true,
                }
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.WebAnalytics,
                        name: `Web analytics`,
                        path: urls.webAnalytics(),
                        iconType: 'web_analytics',
                    },
                    {
                        key: Scene.SessionAttributionExplorer,
                        name: `Session attribution explorer`,
                        path: urls.sessionAttributionExplorer(),
                        iconType: 'web_analytics',
                    },
                ]
            },
        ],
    }),

    actionToUrl(({ values }) => {
        const stateToUrl = (): [string, Record<string, string>] => {
            const { properties, dateRange } = values

            const urlParams = {}
            if (properties.length > 0) {
                urlParams['properties'] = properties
            }
            if (dateRange) {
                urlParams['dateRange'] = dateRange
            }

            return [urls.sessionAttributionExplorer(), urlParams]
        }

        return {
            setProperties: stateToUrl,
            setDateRange: stateToUrl,
        }
    }),

    urlToAction(({ actions }) => ({
        [urls.sessionAttributionExplorer()]: (_, { properties, dateRange }) => {
            const parsedProperties = isSessionPropertyFilters(properties) ? properties : initialProperties
            const parsedDateRange = dateRange ?? null

            actions.setStateFromUrl({
                properties: parsedProperties,
                dateRange: parsedDateRange,
            })
        },
    })),
])
