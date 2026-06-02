import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, LLMTrace, NodeKind, TraceQuery } from '~/queries/schema/schema-general'

import { SortDirection, SortState, aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import type { aiObservabilityGenerationsLogicType } from './aiObservabilityGenerationsLogicType'

export interface AIObservabilityGenerationsLogicProps {
    tabId?: string
}

export function getDefaultGenerationsColumns(showSentiment: boolean = false, showTools: boolean = false): string[] {
    return [
        'uuid',
        'properties.$ai_trace_id',
        'person',
        ...(showSentiment ? ["'' -- Sentiment"] : []),
        "f'{properties.$ai_model}' -- Model",
        ...(showTools ? ['properties.$ai_tools_called'] : []),
        "if(properties.$ai_is_error = 'true', '❌', '') -- Error",
        "f'{round(toFloat(properties.$ai_latency), 2)} s' -- Latency",
        "f'{properties.$ai_input_tokens} → {properties.$ai_output_tokens} (∑ {toInt(properties.$ai_input_tokens) + toInt(properties.$ai_output_tokens)})' -- Token usage",
        "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Cost",
        'timestamp',
    ]
}

export const aiObservabilityGenerationsLogic = kea<aiObservabilityGenerationsLogicType>([
    path(['products', 'ai_observability', 'frontend', 'tabs', 'aiObservabilityGenerationsLogic']),
    // Intentionally not keyed by tabId: the in-app multi-tab feature was removed, so tabId is now a
    // fresh random id per page load. Keying by it would make the persisted column selection's
    // localStorage key change on every refresh, losing the user's choice.
    props({} as AIObservabilityGenerationsLogicProps),
    connect((props: AIObservabilityGenerationsLogicProps) => ({
        values: [
            aiObservabilitySharedLogic({ tabId: props.tabId }),
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            aiObservabilitySharedLogic({ tabId: props.tabId }),
            ['setDates', 'setPropertyFilters', 'setShouldFilterTestAccounts', 'applyUrlState'],
        ],
    })),

    actions({
        setGenerationsQuery: (query: DataTableNode) => ({ query }),
        setGenerationsColumns: (columns: string[]) => ({ columns }),
        setGenerationsSort: (column: string, direction: SortDirection) => ({ column, direction }),
        toggleGenerationExpanded: (uuid: string, traceId: string) => ({ uuid, traceId }),
        setLoadedTrace: (traceId: string, trace: LLMTrace) => ({ traceId, trace }),
        clearExpandedGenerations: true,
    }),

    reducers({
        generationsQueryOverride: [
            null as DataTableNode | null,
            {
                setGenerationsQuery: (_, { query }) => query,
            },
        ],

        generationsColumns: [
            null as string[] | null,
            { persist: true },
            {
                setGenerationsColumns: (_, { columns }) => columns,
            },
        ],

        generationsSort: [
            { column: 'timestamp', direction: 'DESC' } as SortState,
            {
                setGenerationsSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],

        expandedGenerationIds: [
            new Set<string>() as Set<string>,
            {
                toggleGenerationExpanded: (state, { uuid }) => {
                    const newSet = new Set(state)

                    if (newSet.has(uuid)) {
                        newSet.delete(uuid)
                    } else {
                        newSet.add(uuid)
                    }

                    return newSet
                },
                clearExpandedGenerations: () => new Set<string>(),
                setDates: () => new Set<string>(),
                setPropertyFilters: () => new Set<string>(),
                setShouldFilterTestAccounts: () => new Set<string>(),
                applyUrlState: () => new Set<string>(),
            },
        ],

        loadedTraces: [
            {} as Record<string, LLMTrace>,
            {
                setLoadedTrace: (state, { traceId, trace }) => ({
                    ...state,
                    [traceId]: trace,
                }),
                clearExpandedGenerations: () => ({}),
                setDates: () => ({}),
                setPropertyFilters: () => ({}),
                setShouldFilterTestAccounts: () => ({}),
                applyUrlState: () => ({}),
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        toggleGenerationExpanded: async ({ uuid, traceId }) => {
            // Only load if expanding and not already loaded
            if (values.expandedGenerationIds.has(uuid) && !values.loadedTraces[traceId]) {
                // Build TraceQuery with date range from current filters
                const dateFrom = values.dateFilter.dateFrom || '-7d'
                const dateTo = values.dateFilter.dateTo || undefined

                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                    dateRange: {
                        date_from: dateFrom,
                        date_to: dateTo,
                    },
                }

                try {
                    const response = await api.query(traceQuery)

                    if (response.results && response.results.length > 0) {
                        actions.setLoadedTrace(traceId, response.results[0])
                    }
                } catch (error) {
                    console.error('Failed to load trace:', error)
                }
            }
        },
    })),

    selectors({
        generationsQuery: [
            (s) => [s.generationsQueryOverride, s.defaultGenerationsQuery],
            (override, defQuery) => override || defQuery,
        ],

        defaultGenerationsQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.generationsColumns,
                s.generationsSort,
                s.groupsTaxonomicTypes,
                s.featureFlags,
            ],
            (
                dateFilter,
                shouldFilterTestAccounts,
                propertyFilters,
                generationsColumns,
                generationsSort,
                groupsTaxonomicTypes,
                featureFlags
            ): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    limit: 100,
                    select:
                        generationsColumns ||
                        getDefaultGenerationsColumns(
                            !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_SENTIMENT],
                            !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TOOLS_TAB]
                        ),
                    orderBy: [`${generationsSort.column} ${generationsSort.direction}`],
                    after: dateFilter.dateFrom || undefined,
                    before: dateFilter.dateTo || undefined,
                    filterTestAccounts: shouldFilterTestAccounts,
                    event: '$ai_generation',
                    properties: propertyFilters,
                },
                showDateRange: true,
                showReload: true,
                showSearch: true,
                showTestAccountFilters: true,
                showColumnConfigurator: true,
                showPropertyFilter: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
                showExport: true,
                showActions: false,
            }),
        ],
    }),
])
