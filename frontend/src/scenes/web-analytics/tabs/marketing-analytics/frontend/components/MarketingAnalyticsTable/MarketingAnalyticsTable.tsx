import { IconEllipsis, IconSort, IconPlus } from '@posthog/icons'
import { IconArrowUp, IconArrowDown, IconBookmarkBorder } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import {
    MarketingAnalyticsBaseColumns,
    ConversionGoalFilter,
    DataTableNode,
    MarketingAnalyticsTableQuery,
    NodeKind,
    MarketingAnalyticsHelperForColumnNames,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { InsightLogicProps } from '~/types'
import { LemonMenu } from '@posthog/lemon-ui'

import { webAnalyticsDataTableQueryContext } from '../../../../../tiles/WebAnalyticsTile'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { DraftConversionGoalControls } from './DraftConversionGoalControls'

interface MarketingAnalyticsTableProps {
    query: DataTableNode
    insightProps: InsightLogicProps
}

const QUERY_ORDER_BY_START_INDEX = 1

export const MarketingAnalyticsTable = ({ query, insightProps }: MarketingAnalyticsTableProps): JSX.Element => {
    const { setMarketingAnalyticsOrderBy, clearMarketingAnalyticsOrderBy, saveDraftConversionGoal } =
        useActions(marketingAnalyticsLogic)
    const { marketingAnalyticsOrderBy, conversion_goals, draftConversionGoal } = useValues(marketingAnalyticsLogic)
    const { addOrUpdateConversionGoal } = useActions(marketingAnalyticsSettingsLogic)

    // Create a new query object with the orderBy field when sorting state changes
    const queryWithOrderBy = useMemo(() => {
        if (query.source.kind !== NodeKind.MarketingAnalyticsTableQuery) {
            return query
        }

        const source: MarketingAnalyticsTableQuery = {
            ...query.source,
            orderBy: marketingAnalyticsOrderBy ? [marketingAnalyticsOrderBy] : undefined,
        }

        return {
            ...query,
            source,
        }
    }, [query, marketingAnalyticsOrderBy])

    // Combined conversion goals - static from settings + dynamic goal
    const allConversionGoals = useMemo(() => {
        const goals: ConversionGoalFilter[] = []
        if (draftConversionGoal) {
            goals.push(draftConversionGoal)
        }
        if (conversion_goals) {
            goals.push(...conversion_goals)
        }
        return goals
    }, [conversion_goals, draftConversionGoal])

    const makeMarketingSortableCell = useCallback(
        (name: string, index: number, isConversionGoal = false) => {
            return function MarketingSortableCellComponent() {
                const [orderIndex, orderDirection] = marketingAnalyticsOrderBy || [null, null]
                const isSortedByMyField = orderIndex === index
                const isAscending = orderDirection === 'ASC'
                const isDescending = orderDirection === 'DESC'

                const menuItems = [
                    {
                        title: 'Sorting',
                        icon: <IconSort />,
                        items: [
                            {
                                label: 'Sort ascending',
                                icon: <IconArrowUp />,
                                onClick: () => setMarketingAnalyticsOrderBy(index, 'ASC'),
                                disabled: isSortedByMyField && isAscending,
                            },
                            {
                                label: 'Sort descending',
                                icon: <IconArrowDown />,
                                onClick: () => setMarketingAnalyticsOrderBy(index, 'DESC'),
                                disabled: isSortedByMyField && isDescending,
                            },
                            ...(isSortedByMyField
                                ? [
                                      {
                                          label: 'Clear sort',
                                          onClick: () => clearMarketingAnalyticsOrderBy(),
                                      },
                                  ]
                                : []),
                        ],
                    },
                    // Add save option for conversion goal columns
                    ...(isConversionGoal
                        ? [
                              {
                                  title: 'Actions',
                                  items: [
                                      {
                                          label: 'Save as conversion goal',
                                          icon: <IconBookmarkBorder />,
                                          onClick: () => {
                                              if (draftConversionGoal) {
                                                  addOrUpdateConversionGoal(draftConversionGoal)
                                                  saveDraftConversionGoal()
                                              }
                                          },
                                      },
                                  ],
                              },
                          ]
                        : []),
                ]

                const icon = isConversionGoal ? (
                    <IconPlus className="ml-1 group-hover:hidden" />
                ) : isSortedByMyField ? (
                    isAscending ? (
                        <IconArrowUp className="ml-1 group-hover:hidden" />
                    ) : (
                        <IconArrowDown className="ml-1 group-hover:hidden" />
                    )
                ) : null

                return (
                    <LemonMenu items={menuItems}>
                        <span className="group cursor-pointer inline-flex items-center">
                            {name}
                            {icon ? (
                                <>
                                    {icon} <IconEllipsis className="ml-1 hidden group-hover:inline" />
                                </>
                            ) : (
                                <IconEllipsis className="ml-1 opacity-0 group-hover:opacity-100" />
                            )}
                        </span>
                    </LemonMenu>
                )
            }
        },
        [
            marketingAnalyticsOrderBy,
            setMarketingAnalyticsOrderBy,
            clearMarketingAnalyticsOrderBy,
            draftConversionGoal,
            addOrUpdateConversionGoal,
            saveDraftConversionGoal,
        ]
    )

    const conversionGoalColumns = useMemo(() => {
        const columns: Record<string, QueryContextColumn> = {}

        allConversionGoals?.forEach((goal: ConversionGoalFilter, index: number) => {
            const goalName = goal.conversion_goal_name || `${MarketingAnalyticsHelperForColumnNames.Goal} ${index + 1}`
            const costPerGoalName = `${MarketingAnalyticsHelperForColumnNames.CostPer} ${goalName}`

            // Each conversion goal creates 2 columns (goal count + cost per goal), hence index * 2
            const goalColumnIndex =
                Object.keys(MarketingAnalyticsBaseColumns).length + index * 2 + QUERY_ORDER_BY_START_INDEX
            const costColumnIndex =
                Object.keys(MarketingAnalyticsBaseColumns).length + index * 2 + QUERY_ORDER_BY_START_INDEX + 1

            // Check if this is the dynamic conversion goal (the one being created/edited)
            const isDraftConversionGoal = goal === draftConversionGoal

            // Add conversion count column
            columns[goalName] = {
                renderTitle: makeMarketingSortableCell(goalName, goalColumnIndex, isDraftConversionGoal),
                align: 'right',
            }

            // Add cost per conversion column
            columns[costPerGoalName] = {
                renderTitle: makeMarketingSortableCell(costPerGoalName, costColumnIndex, isDraftConversionGoal),
                align: 'right',
            }
        })

        return columns
    }, [allConversionGoals, makeMarketingSortableCell, draftConversionGoal])

    // Create custom context with sortable headers for marketing analytics
    const marketingAnalyticsContext: QueryContext = {
        ...webAnalyticsDataTableQueryContext,
        insightProps,
        columns: {
            ...webAnalyticsDataTableQueryContext.columns,
            // Indexes start at 1 because the orderBy field is 1-indexed e.g ORDER BY 1 DESC would sort by the first column
            ...Object.values(MarketingAnalyticsBaseColumns).reduce((acc, column, index) => {
                acc[column] = {
                    renderTitle: makeMarketingSortableCell(column, index + QUERY_ORDER_BY_START_INDEX),
                }
                return acc
            }, {} as Record<string, QueryContextColumn>),
            ...conversionGoalColumns,
        },
    }

    return (
        <div className="bg-surface-primary">
            <div className="p-4 border-b border-border bg-bg-light">
                <DraftConversionGoalControls />
            </div>
            <div className="relative marketing-analytics-table-container">
                <Query query={queryWithOrderBy} readOnly={false} context={marketingAnalyticsContext} />
            </div>
        </div>
    )
}
