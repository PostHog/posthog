import { actions, connect, kea, path, props, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import errorsQueryTemplate from '../../backend/queries/errors.sql?raw'
import { SortDirection, SortState, aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import type { aiObservabilityErrorsLogicType } from './aiObservabilityErrorsLogicType'

export type AIObservabilityErrorsLogicProps = Record<string, never>

export const aiObservabilityErrorsLogic = kea<aiObservabilityErrorsLogicType>([
    path(['products', 'ai_observability', 'frontend', 'tabs', 'aiObservabilityErrorsLogic']),
    props({} as AIObservabilityErrorsLogicProps),
    connect(() => ({
        values: [
            aiObservabilitySharedLogic,
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    })),

    actions({
        setErrorsSort: (column: string, direction: SortDirection) => ({ column, direction }),
    }),

    reducers({
        errorsSort: [
            { column: 'traces', direction: 'DESC' } as SortState,
            {
                setErrorsSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
    }),

    selectors({
        errorsQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters, s.errorsSort, s.groupsTaxonomicTypes],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                errorsSort: SortState,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[]
            ): DataTableNode => {
                // Use the shared query template
                // Simple placeholder replacement - no escaping needed
                const query = errorsQueryTemplate
                    .replace('__ORDER_BY__', errorsSort.column)
                    .replace('__ORDER_DIRECTION__', errorsSort.direction)

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query,
                        filters: {
                            dateRange: {
                                date_from: dateFilter.dateFrom || null,
                                date_to: dateFilter.dateTo || null,
                            },
                            filterTestAccounts: shouldFilterTestAccounts,
                            properties: propertyFilters,
                        },
                    },
                    columns: [
                        'error',
                        'traces',
                        'generations',
                        'spans',
                        'embeddings',
                        'sessions',
                        'users',
                        'days_seen',
                        'first_seen',
                        'last_seen',
                    ],
                    showDateRange: true,
                    showReload: true,
                    showSearch: true,
                    showPropertyFilter: [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ],
                    showTestAccountFilters: true,
                    showExport: true,
                    showColumnConfigurator: true,
                    allowSorting: true,
                }
            },
        ],
        buildErrorTrendQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): ((errorName: string) => TrendsQuery) => {
                return (errorName: string): TrendsQuery => ({
                    kind: NodeKind.TrendsQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || null,
                        date_to: dateFilter.dateTo || null,
                    },
                    filterTestAccounts: shouldFilterTestAccounts,
                    properties: [
                        ...propertyFilters,
                        {
                            key: '$ai_is_error',
                            operator: PropertyOperator.Exact,
                            value: 'true',
                            type: PropertyFilterType.Event,
                        },
                        {
                            key: '$ai_error_normalized',
                            operator: PropertyOperator.Exact,
                            value: errorName,
                            type: PropertyFilterType.Event,
                        },
                    ],
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_generation',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_span',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_trace',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_embedding',
                        },
                    ],
                })
            },
        ],
        buildAllErrorsTrendQuery: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[]
            ): InsightVizNode => ({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || null,
                        date_to: dateFilter.dateTo || null,
                    },
                    filterTestAccounts: shouldFilterTestAccounts,
                    properties: [
                        ...propertyFilters,
                        {
                            key: '$ai_is_error',
                            operator: PropertyOperator.Exact,
                            value: 'true',
                            type: PropertyFilterType.Event,
                        },
                    ],
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_generation',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_span',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_trace',
                        },
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_embedding',
                        },
                    ],
                    breakdownFilter: {
                        breakdown: '$ai_error_normalized',
                        breakdown_type: 'event',
                        breakdown_limit: 10,
                    },
                },
            }),
        ],
    }),
])
