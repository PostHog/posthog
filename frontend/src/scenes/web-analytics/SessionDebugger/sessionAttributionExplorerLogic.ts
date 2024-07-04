import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { DataTableNode, HogQLQuery, NodeKind } from '~/queries/schema'
import { isSessionPropertyFilters } from '~/queries/schema-guards'
import { SessionPropertyFilter } from '~/types'

import type { sessionAttributionExplorerLogicType } from './sessionAttributionExplorerLogicType'

export const initialFilters = [] as SessionPropertyFilter[]
export const sessionAttributionExplorerLogic = kea<sessionAttributionExplorerLogicType>([
    path(['scenes', 'webAnalytics', 'sessionDebuggerLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setFilters: (filters: SessionPropertyFilter[]) => ({ filters }),
        setStateFromUrl: (state: { filters: SessionPropertyFilter[] }) => ({
            state,
        }),
    }),
    reducers({
        filters: [
            initialFilters,
            {
                setFilters: (_, { filters }) => filters,
                setStateFromUrl: (_, { state }) => state.filters,
            },
        ],
    }),
    selectors({
        query: [
            (s) => [s.filters],
            (filters: SessionPropertyFilter[]): DataTableNode => {
                const source: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    filters: {
                        properties: filters,
                    },
                    query: `
SELECT
    "$entry_referring_domain" as 'context.columns.referring_domain',
    "$entry_utm_source" as 'context.columns.utm_source',
    "$entry_utm_medium" as 'context.columns.utm_medium',
    "$entry_utm_campaign" as 'context.columns.utm_campaign',
    nullIf(arrayStringConcat([
        if(isNotNull($entry_gclid), 'glcid', NULL),
        if(isNotNull($entry_gad_source), 'gad_source', NULL)
        -- add more here if we add more ad ids
    ], ','), '') as 'context.columns.has_ad_id',
    topK(10)($entry_current_url) as 'context.columns.example_entry_urls',
    "$channel_type" as 'context.columns.channel_type',
    count() as 'context.columns.count'
FROM sessions
WHERE $start_timestamp >= now() - toIntervalDay(7) AND {filters}
GROUP BY 1,2,3,4,5,7
ORDER BY 8 DESC
`,
                }
                return {
                    kind: NodeKind.DataTableNode,
                    source: source,
                    showPropertyFilter: [TaxonomicFilterGroupType.SessionProperties],
                    showOpenEditorButton: true,
                    showReload: true,
                }
            },
        ],
    }),

    actionToUrl(({ values }) => {
        const stateToUrl = (): string => {
            const { filters } = values

            const urlParams = new URLSearchParams()
            if (filters.length > 0) {
                urlParams.set('filters', JSON.stringify(filters))
            }

            return `${urls.sessionAttributionExplorer()}?${urlParams.toString()}`
        }

        return {
            setFilters: stateToUrl,
        }
    }),

    urlToAction(({ actions }) => ({
        [urls.sessionAttributionExplorer()]: (_, { filters }) => {
            const parsedFilters = isSessionPropertyFilters(filters) ? filters : initialFilters

            actions.setStateFromUrl({
                filters: parsedFilters,
            })
        },
    })),
])
