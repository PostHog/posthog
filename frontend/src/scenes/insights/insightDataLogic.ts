import { actions, connect, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { promptLogic } from 'lib/logic/promptLogic'
import { objectsEqual } from 'lib/utils'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/project/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightTypeToDefaultQuery, nodeKindToDefaultQuery } from '~/queries/nodes/InsightQuery/defaults'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { queryExportContext } from '~/queries/query'
import { InsightNodeKind, InsightVizNode, Node, NodeKind } from '~/queries/schema'
import { isInsightVizNode } from '~/queries/utils'
import { FilterType, InsightLogicProps, InsightType } from '~/types'

import type { insightDataLogicType } from './insightDataLogicType'
import { insightDataTimingLogic } from './insightDataTimingLogic'
import { insightLogic } from './insightLogic'
import { cleanFilters, setTestAccountFilterForNewInsight } from './utils/cleanFilters'
import { compareFilters } from './utils/compareFilters'

const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

export const queryFromKind = (kind: InsightNodeKind, filterTestAccountsDefault: boolean): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: { ...nodeKindToDefaultQuery[kind], ...(filterTestAccountsDefault ? { filterTestAccounts: true } : {}) },
})

export const insightDataLogic = kea<insightDataLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'insightDataLogic', key]),

    connect((props: InsightLogicProps) => ({
        values: [
            insightLogic,
            ['filters', 'insight', 'savedInsight'],
            dataNodeLogic({
                key: insightVizDataNodeKey(props),
                loadPriority: props.loadPriority,
            } as DataNodeLogicProps),
            [
                'query as insightQuery',
                'response as insightDataRaw',
                'dataLoading as insightDataLoading',
                'responseErrorObject as insightDataError',
                'getInsightRefreshButtonDisabledReason',
            ],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [
            insightLogic,
            [
                'setInsight',
                'loadInsightSuccess',
                'saveInsight as insightLogicSaveInsight',
                'saveAsNamingSuccess as insightLogicSaveAsNamingSuccess',
            ],
            dataNodeLogic({ key: insightVizDataNodeKey(props) } as DataNodeLogicProps),
            ['loadData', 'loadDataSuccess', 'loadDataFailure', 'setResponse as setInsightData'],
        ],
        logic: [insightDataTimingLogic(props), promptLogic({ key: `save-as-insight` })],
    })),

    actions({
        setQuery: (query: Node | null) => ({ query }),
        saveAs: true,
        saveAsNamingSuccess: (name: string) => ({ name }),
        saveInsight: (redirectToViewMode = true) => ({ redirectToViewMode }),
        toggleQueryEditorPanel: true,
        cancelChanges: true,
    }),

    reducers({
        internalQuery: [
            null as Node | null,
            {
                setQuery: (_, { query }) => query,
            },
        ],
        showQueryEditor: [
            false,
            {
                toggleQueryEditorPanel: (state) => !state,
            },
        ],
    }),

    selectors({
        query: [
            (s) => [s.propsQuery, s.filters, s.insight, s.internalQuery, s.filterTestAccountsDefault],
            (propsQuery, filters, insight, internalQuery, filterTestAccountsDefault) =>
                propsQuery ||
                internalQuery ||
                insight.query ||
                (filters && filters.insight ? queryFromFilters(filters) : undefined) ||
                queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault),
        ],

        propsQuery: [
            () => [(_, props) => props],
            // overwrite query from props for standalone InsightVizNode queries
            (props: InsightLogicProps) => (props.dashboardItemId?.startsWith('new-AdHoc.') ? props.query : null),
        ],

        isQueryBasedInsight: [
            (s) => [s.query],
            (query) => {
                return !!query && !isInsightVizNode(query)
            },
        ],

        exportContext: [
            (s) => [s.query, s.insight],
            (query, insight) => {
                if (!query) {
                    // if we're here without a query then an empty query context is not the problem
                    return undefined
                }
                const filename = ['export', insight.name || insight.derived_name].join('-')
                return { ...queryExportContext(query), filename }
            },
        ],

        queryChanged: [
            (s) => [s.isQueryBasedInsight, s.query, s.insight, s.savedInsight, s.currentTeam],
            (isQueryBasedInsight, query, insight, savedInsight, currentTeam) => {
                if (isQueryBasedInsight) {
                    return !objectsEqual(query, insight.query)
                } else {
                    const currentFilters = queryNodeToFilter((query as InsightVizNode).source)

                    let savedFilters: Partial<FilterType>
                    if (savedInsight.filters) {
                        savedFilters = savedInsight.filters
                    } else {
                        savedFilters = queryNodeToFilter(
                            insightTypeToDefaultQuery[currentFilters.insight || InsightType.TRENDS]
                        )
                        setTestAccountFilterForNewInsight(
                            savedFilters,
                            currentTeam?.test_account_filters_default_checked
                        )
                    }

                    return !compareFilters(
                        currentFilters,
                        savedFilters,
                        currentTeam?.test_account_filters_default_checked
                    )
                }
            },
        ],

        insightData: [
            (s) => [s.insightDataRaw],
            (insightDataRaw): Record<string, any> => {
                // :TRICKY: The queries return results as `results`, but insights expect `result`
                return { ...insightDataRaw, result: insightDataRaw?.results ?? insightDataRaw?.result }
            },
        ],

        hogQL: [
            (s) => [s.insightData],
            (insightData): string | null => {
                if (insightData && 'hogql' in insightData && insightData.hogql !== '') {
                    return insightData.hogql
                }
                return null
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setInsight: ({ insight: { filters, query, result }, options: { overrideFilter } }) => {
            if (overrideFilter && query == null) {
                actions.setQuery(queryFromFilters(cleanFilters(filters || {})))
            } else if (query) {
                actions.setQuery(query)
            }

            if (result) {
                actions.setInsightData({ ...values.insightData, result })
            }
        },
        loadInsightSuccess: ({ insight }) => {
            if (insight.query) {
                actions.setQuery(insight.query)
            } else if (!!insight.filters && !!Object.keys(insight.filters).length) {
                const query = queryFromFilters(insight.filters)
                actions.setQuery(query)
            }
        },
        saveInsight: ({ redirectToViewMode }) => {
            let filters = values.insight.filters
            if (isInsightVizNode(values.query)) {
                const querySource = values.query.source
                filters = queryNodeToFilter(querySource)
            } else if (values.isQueryBasedInsight) {
                filters = {}
            }

            let query = undefined
            if (values.isQueryBasedInsight) {
                query = values.query
            }

            actions.setInsight(
                {
                    ...values.insight,
                    filters: filters,
                    query: query ?? undefined,
                },
                { overrideFilter: true, fromPersistentApi: false }
            )

            actions.insightLogicSaveInsight(redirectToViewMode)
        },
        saveAs: async () => {
            promptLogic({ key: `save-as-insight` }).actions.prompt({
                title: 'Save as new insight',
                placeholder: 'Please enter the new name',
                value: `${values.insight.name || values.insight.derived_name} (copy)`,
                error: 'You must enter a name',
                success: actions.saveAsNamingSuccess,
            })
        },
        saveAsNamingSuccess: ({ name }) => {
            let filters = values.insight.filters
            if (isInsightVizNode(values.query)) {
                const querySource = values.query.source
                filters = queryNodeToFilter(querySource)
            } else if (values.isQueryBasedInsight) {
                filters = {}
            }

            let query = undefined
            if (values.isQueryBasedInsight) {
                query = values.query
            }

            actions.setInsight(
                {
                    ...values.insight,
                    filters: filters,
                    query: query ?? undefined,
                },
                { overrideFilter: true, fromPersistentApi: false }
            )

            actions.insightLogicSaveAsNamingSuccess(name)
        },
        cancelChanges: () => {
            const savedFilters = values.savedInsight.filters
            const savedResult = values.savedInsight.result
            actions.setQuery(savedFilters ? queryFromFilters(savedFilters) : null)
            actions.setInsightData({ ...values.insightData, result: savedResult ? savedResult : null })
        },
    })),
    propsChanged(({ actions, props, values }) => {
        if (props.cachedInsight?.query && !objectsEqual(props.cachedInsight.query, values.query)) {
            actions.setQuery(props.cachedInsight.query)
        }
    }),
])
