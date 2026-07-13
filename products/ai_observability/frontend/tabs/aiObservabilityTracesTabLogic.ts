import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import { buildAiObservabilityStorageConfig } from '../preferenceStorage'
import { LLM_TRACES_PAGE_SIZE } from '../utils'
import type { aiObservabilityTracesTabLogicType } from './aiObservabilityTracesTabLogicType'

export interface AIObservabilityTracesTabLogicProps {
    personId?: string
    group?: {
        groupKey: string
        groupTypeIndex: number
    }
}

export const aiObservabilityTracesTabLogic = kea<aiObservabilityTracesTabLogicType>([
    path(['products', 'ai_observability', 'frontend', 'tabs', 'aiObservabilityTracesTabLogic']),
    key((props: AIObservabilityTracesTabLogicProps) => props?.personId || 'aiObservabilityScene'),
    props({} as AIObservabilityTracesTabLogicProps),
    connect((props: AIObservabilityTracesTabLogicProps) => ({
        values: [
            aiObservabilitySharedLogic({ personId: props.personId, group: props.group }),
            ['dateFilter', 'shouldFilterTestAccounts', 'shouldFilterSupportTraces', 'propertyFilters', 'searchQuery'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user'],
        ],
    })),

    actions({
        setTracesQuery: (query: DataTableNode) => ({ query }),
        setShowInputOutputColumns: (show: boolean) => ({ show }),
        setShowSentimentColumn: (show: boolean) => ({ show }),
    }),

    reducers(() => ({
        tracesQueryOverride: [
            null as DataTableNode | null,
            {
                setTracesQuery: (_, { query }) => query,
            },
        ],
        showInputOutputColumns: [
            true as boolean,
            buildAiObservabilityStorageConfig('traces.showInputOutputColumns'),
            {
                setShowInputOutputColumns: (_, { show }) => show,
            },
        ],
        showSentimentColumn: [
            true as boolean,
            buildAiObservabilityStorageConfig('traces.showSentimentColumn'),
            {
                setShowSentimentColumn: (_, { show }) => show,
            },
        ],
    })),

    selectors({
        tracesQuery: [
            (s) => [s.tracesQueryOverride, s.defaultTracesQuery],
            (override, defQuery) => override || defQuery,
        ],

        defaultTracesQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.shouldFilterSupportTraces,
                s.propertyFilters,
                s.searchQuery,
                (_, props) => props.personId,
                (_, props) => props.group,
                s.groupsTaxonomicTypes,
                s.featureFlags,
                s.user,
                s.showInputOutputColumns,
                s.showSentimentColumn,
            ],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                shouldFilterSupportTraces: boolean,
                propertyFilters,
                searchQuery: string,
                personId: string | undefined,
                group: { groupKey: string; groupTypeIndex: number } | undefined,
                groupsTaxonomicTypes: TaxonomicFilterGroupType[],
                featureFlags: { [flag: string]: boolean | string | undefined },
                user: { is_impersonated?: boolean } | null,
                showInputOutputColumns: boolean,
                showSentimentColumn: boolean
            ): DataTableNode => {
                // For impersonated users (support agents), default to showing support traces
                // For regular users, always filter out support traces
                const filterSupportTraces = user?.is_impersonated ? shouldFilterSupportTraces : true

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.TracesQuery,
                        limit: LLM_TRACES_PAGE_SIZE,
                        dateRange: {
                            date_from: dateFilter.dateFrom || undefined,
                            date_to: dateFilter.dateTo || undefined,
                        },
                        filterTestAccounts: shouldFilterTestAccounts ?? false,
                        filterSupportTraces,
                        properties: propertyFilters,
                        searchTerm: featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_TRACE_SEARCH]
                            ? searchQuery || undefined
                            : undefined,
                        personId: personId ?? undefined,
                        groupKey: group?.groupKey,
                        groupTypeIndex: group?.groupTypeIndex,
                        includeSentiment: showSentimentColumn,
                    },
                    columns: [
                        'id',
                        'traceName',
                        ...(showInputOutputColumns ? ['inputState', 'outputState'] : []),
                        'person',
                        ...(showSentimentColumn ? ['__llm_sentiment'] : []),
                        '__llm_tools',
                        'errorCount',
                        'totalLatency',
                        'usage',
                        'totalCost',
                        'review',
                        'createdAt',
                    ],
                    showDateRange: true,
                    showReload: true,
                    showSearch: !!featureFlags[FEATURE_FLAGS.LLM_OBSERVABILITY_TRACE_SEARCH],
                    showTestAccountFilters: true,
                    showExport: false,
                    showOpenEditorButton: false,
                    showColumnConfigurator: false,
                    showPropertyFilter: [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ],
                }
            },
        ],
    }),
])
