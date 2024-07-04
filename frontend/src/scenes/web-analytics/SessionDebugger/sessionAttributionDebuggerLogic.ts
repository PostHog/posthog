import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { DataTableNode, HogQLQuery, NodeKind } from '~/queries/schema'
import { isSessionPropertyFilters } from '~/queries/schema-guards'
import { SessionPropertyFilter } from '~/types'

import type { sessionAttributionDebuggerLogicType } from './sessionAttributionDebuggerLogicType'

export const initialFilters = [] as SessionPropertyFilter[]
export const sessionAttributionDebuggerLogic = kea<sessionAttributionDebuggerLogicType>([
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
    "$channel_type" as 'context.columns.channel_type',
    count() as 'context.columns.count',
    "$entry_referring_domain" as 'context.columns.referring_domain',
    "$entry_utm_source" as 'context.columns.utm_source',
    "$entry_utm_medium" as 'context.columns.utm_medium',
    "$entry_utm_campaign" as 'context.columns.utm_campaign',
    if("$entry_gclid" IS NOT NULL OR "$entry_gad_source"  IS NOT NULL, 'true', 'false') as 'context.columns.has_ad_id',
    topK(10)($entry_current_url) as 'context.columns.example_entry_urls'
FROM sessions
WHERE $start_timestamp >= now() - toIntervalDay(7) AND {filters}
GROUP BY 1, 3, 4, 5, 6, 7
ORDER BY 2 DESC
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

            return `${urls.sessionAttributionDebugger()}?${urlParams.toString()}`
        }

        return {
            setFilters: stateToUrl,
        }
    }),

    urlToAction(({ actions }) => ({
        [urls.sessionAttributionDebugger()]: (_, { filters }) => {
            const parsedFilters = isSessionPropertyFilters(filters) ? filters : initialFilters

            actions.setStateFromUrl({
                filters: parsedFilters,
            })
        },
    })),
])
