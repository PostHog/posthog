import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { DataTableNode, DateRange, HogQLQuery, NodeKind } from '~/queries/schema'
import { isSessionPropertyFilters } from '~/queries/schema-guards'
import { SessionPropertyFilter } from '~/types'

import type { sessionAttributionExplorerLogicType } from './sessionAttributionExplorerLogicType'

export const initialProperties = [] as SessionPropertyFilter[]
export const defaultDateRange: DateRange = { date_from: '-7d', date_to: 'now' }
export const sessionAttributionExplorerLogic = kea<sessionAttributionExplorerLogicType>([
    path(['scenes', 'webAnalytics', 'sessionDebuggerLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setProperties: (properties: SessionPropertyFilter[]) => ({ properties }),
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setStateFromUrl: (state: { properties: SessionPropertyFilter[]; dateRange: DateRange | null }) => ({
            state,
        }),
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
    }),
    selectors({
        query: [
            (s) => [s.properties, s.dateRange],
            (properties: SessionPropertyFilter[], dateRange): DataTableNode => {
                const source: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    filters: {
                        properties,
                        dateRange: dateRange ?? defaultDateRange,
                    },
                    query: `
SELECT
    count() as "context.columns.count",
    "$channel_type" as "context.columns.channel_type",
    "$entry_referring_domain" as "context.columns.referring_domain",
    "$entry_utm_source" as "context.columns.utm_source",
    "$entry_utm_medium" as "context.columns.utm_medium",
    "$entry_utm_campaign" as "context.columns.utm_campaign",
    nullIf(arrayStringConcat([
        if(isNotNull($entry_gclid), 'glcid', NULL),
        if(isNotNull($entry_gad_source), 'gad_source', NULL)
        -- add more here if we add more ad ids
    ], ','), '') as "context.columns.has_ad_id",
    topK(10)($entry_current_url) as "context.columns.example_entry_urls"
FROM sessions
WHERE {filters}
GROUP BY
    "context.columns.referring_domain",
    "context.columns.utm_source",
    "context.columns.utm_medium",
    "context.columns.utm_campaign",
    "context.columns.has_ad_id",
    "context.columns.channel_type"
ORDER BY 
    "context.columns.count" DESC
`,
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
