import { IconChevronDown } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import {
    ConversionGoalFilter,
    DataTableNode,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

interface ColumnConfig {
    renderTitle?: QueryContextColumnTitleComponent
    render?: ({ value }: { value: any }) => React.ReactNode
    align?: 'left' | 'center' | 'right'
}

import { webAnalyticsDataTableQueryContext } from '../../../../../tiles/WebAnalyticsTile'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import {
    CAMPAIGN_COST_CTE_NAME,
    CAMPAIGN_NAME_FIELD,
    CONVERSION_GOAL_PREFIX,
    CONVERSION_GOAL_PREFIX_ABBREVIATION,
    SOURCE_NAME_FIELD,
    TOTAL_CLICKS_FIELD,
    TOTAL_COST_FIELD,
    TOTAL_IMPRESSIONS_FIELD,
} from '../../logic/utils'
import { DynamicConversionGoalControls } from './DynamicConversionGoalControls'

interface MarketingAnalyticsTableProps {
    query: DataTableNode
    insightProps: InsightLogicProps
}

// TODO: refactor this component to support column actions (`...` button) to be more explicit on the different actions
// Also we need to centralize the column names and orderBy fields whether in the backend or frontend
export const MarketingAnalyticsTable = ({ query, insightProps }: MarketingAnalyticsTableProps): JSX.Element => {
    const { setMarketingAnalyticsOrderBy, clearMarketingAnalyticsOrderBy } = useActions(marketingAnalyticsLogic)
    const { marketingAnalyticsOrderBy, conversion_goals, dynamicConversionGoal } = useValues(marketingAnalyticsLogic)

    // Create a new query object with the orderBy field when sorting state changes
    const queryWithOrderBy = useMemo(() => {
        if (query.source.kind !== NodeKind.MarketingAnalyticsTableQuery) {
            return query
        }

        const source: MarketingAnalyticsTableQuery = {
            ...query.source,
            orderBy: marketingAnalyticsOrderBy
                ? [`${marketingAnalyticsOrderBy[0]} ${marketingAnalyticsOrderBy[1]}`]
                : undefined,
        }

        return {
            ...query,
            source,
        }
    }, [query, marketingAnalyticsOrderBy])

    // Combined conversion goals - static from settings + dynamic goal
    const allConversionGoals = useMemo(() => {
        const goals: ConversionGoalFilter[] = []
        if (dynamicConversionGoal) {
            goals.push(dynamicConversionGoal)
        }
        if (conversion_goals) {
            goals.push(...conversion_goals)
        }
        return goals
    }, [conversion_goals, dynamicConversionGoal])

    const MarketingSortableCell = useCallback(
        (name: string, orderByField: string): QueryContextColumnTitleComponent =>
            function MarketingSortableCell() {
                const isSortedByMyField = marketingAnalyticsOrderBy?.[0] === orderByField
                const isAscending = marketingAnalyticsOrderBy?.[1] === 'ASC'
                const isDescending = marketingAnalyticsOrderBy?.[1] === 'DESC'

                const onClick = useCallback(() => {
                    // 3-state cycle: None -> DESC -> ASC -> None (clear/reset to default)
                    if (!isSortedByMyField) {
                        // Not currently sorted by this field, start with DESC
                        setMarketingAnalyticsOrderBy(orderByField, 'DESC')
                    } else if (isDescending) {
                        // Currently DESC, change to ASC
                        setMarketingAnalyticsOrderBy(orderByField, 'ASC')
                    } else if (isAscending) {
                        // Currently ASC, clear the sort (reset to default order)
                        clearMarketingAnalyticsOrderBy()
                    }
                }, [isSortedByMyField, isAscending, isDescending])

                return (
                    <span onClick={onClick} className="group cursor-pointer inline-flex items-center">
                        {name}
                        <IconChevronDown
                            fontSize="20px"
                            className={clsx('-mr-1 ml-1 text-muted-alt opacity-0 group-hover:opacity-100', {
                                'text-primary opacity-100': isSortedByMyField,
                                'rotate-180': isSortedByMyField && isAscending,
                            })}
                        />
                    </span>
                )
            },
        [marketingAnalyticsOrderBy, setMarketingAnalyticsOrderBy, clearMarketingAnalyticsOrderBy]
    )

    const conversionGoalColumns = useMemo(() => {
        const columns: Record<string, ColumnConfig> = {}

        allConversionGoals?.forEach((goal: ConversionGoalFilter, index: number) => {
            const goalName = goal.conversion_goal_name || `Goal ${index + 1}`
            const costPerGoalName = `Cost per ${goalName}`

            // Add conversion count column
            columns[goalName] = {
                renderTitle: MarketingSortableCell(
                    goalName,
                    `${CONVERSION_GOAL_PREFIX_ABBREVIATION}${index}.${CONVERSION_GOAL_PREFIX}${index}`
                ),
                render: ({ value }: { value: any }) => value || '-',
                align: 'right',
            }

            // Add cost per conversion column
            columns[costPerGoalName] = {
                renderTitle: MarketingSortableCell(
                    costPerGoalName,
                    `${CAMPAIGN_COST_CTE_NAME}.${TOTAL_COST_FIELD} / nullif(${CONVERSION_GOAL_PREFIX_ABBREVIATION}${index}.${CONVERSION_GOAL_PREFIX}${index}, 0)`
                ),
                render: ({ value }: { value: any }) =>
                    value && typeof value === 'number' ? `$${value.toFixed(2)}` : '-',
                align: 'right',
            }
        })

        return columns
    }, [allConversionGoals, MarketingSortableCell])

    // Create custom context with sortable headers for marketing analytics
    const marketingAnalyticsContext: QueryContext = {
        ...webAnalyticsDataTableQueryContext,
        insightProps,
        columns: {
            ...webAnalyticsDataTableQueryContext.columns,
            // Add sortable column headers for marketing analytics fields
            // These match the backend output column names
            Campaign: {
                renderTitle: MarketingSortableCell('Campaign', `${CAMPAIGN_COST_CTE_NAME}.${CAMPAIGN_NAME_FIELD}`),
            },
            Source: {
                renderTitle: MarketingSortableCell('Source', `${CAMPAIGN_COST_CTE_NAME}.${SOURCE_NAME_FIELD}`),
            },
            'Total Cost': {
                renderTitle: MarketingSortableCell('Total Cost', `${CAMPAIGN_COST_CTE_NAME}.${TOTAL_COST_FIELD}`),
                render: webAnalyticsDataTableQueryContext.columns?.cost?.render,
                align: 'right',
            },
            'Total Clicks': {
                renderTitle: MarketingSortableCell('Total Clicks', `${CAMPAIGN_COST_CTE_NAME}.${TOTAL_CLICKS_FIELD}`),
                render: webAnalyticsDataTableQueryContext.columns?.clicks?.render,
                align: 'right',
            },
            'Total Impressions': {
                renderTitle: MarketingSortableCell(
                    'Total Impressions',
                    `${CAMPAIGN_COST_CTE_NAME}.${TOTAL_IMPRESSIONS_FIELD}`
                ),
                render: webAnalyticsDataTableQueryContext.columns?.impressions?.render,
                align: 'right',
            },
            'Cost per Click': {
                renderTitle: MarketingSortableCell(
                    'Cost per Click',
                    `${CAMPAIGN_COST_CTE_NAME}.${TOTAL_COST_FIELD} / nullif(${CAMPAIGN_COST_CTE_NAME}.${TOTAL_CLICKS_FIELD}, 0)`
                ),
                render: webAnalyticsDataTableQueryContext.columns?.cpc?.render,
                align: 'right',
            },
            CTR: {
                renderTitle: MarketingSortableCell(
                    'CTR',
                    `${CAMPAIGN_COST_CTE_NAME}.${TOTAL_CLICKS_FIELD} / nullif(${CAMPAIGN_COST_CTE_NAME}.${TOTAL_IMPRESSIONS_FIELD}, 0) * 100`
                ),
                render: webAnalyticsDataTableQueryContext.columns?.ctr?.render,
                align: 'right',
            },
            ...conversionGoalColumns,
        },
    }

    return (
        <div className="bg-surface-primary">
            <div className="p-4 border-b border-border bg-bg-light">
                <DynamicConversionGoalControls />
            </div>
            <Query query={queryWithOrderBy} readOnly={false} context={marketingAnalyticsContext} />
        </div>
    )
}
