import { IconChevronDown } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, MarketingAnalyticsTableQuery } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { webAnalyticsDataTableQueryContext } from '../../../../tiles/WebAnalyticsTile'
import { marketingAnalyticsLogic } from '../logic/marketingAnalyticsLogic'

interface MarketingAnalyticsTableProps {
    query: DataTableNode
    insightProps: InsightLogicProps
}

export const MarketingAnalyticsTable = ({ query, insightProps }: MarketingAnalyticsTableProps): JSX.Element => {
    const { setMarketingAnalyticsOrderBy, clearMarketingAnalyticsOrderBy } = useActions(marketingAnalyticsLogic)
    const { marketingAnalyticsOrderBy, conversion_goals } = useValues(marketingAnalyticsLogic)

    // Create a new query object with the orderBy field when sorting state changes
    const queryWithOrderBy = useMemo(() => {
        if (query.source.kind !== 'MarketingAnalyticsTableQuery') {
            return query
        }

        return {
            ...query,
            source: {
                ...query.source,
                orderBy: marketingAnalyticsOrderBy ? [`${marketingAnalyticsOrderBy[0]} ${marketingAnalyticsOrderBy[1]}`] : undefined,
            } as MarketingAnalyticsTableQuery
        }
    }, [query, marketingAnalyticsOrderBy])

    // Custom sortable cell component for marketing analytics
    const MarketingSortableCell = (name: string, orderByField: string): QueryContextColumnTitleComponent =>
        function MarketingSortableCell() {
            const isSortedByMyField = marketingAnalyticsOrderBy?.[0] === orderByField
            const isAscending = marketingAnalyticsOrderBy?.[1] === 'ASC'
            const isDescending = marketingAnalyticsOrderBy?.[1] === 'DESC'

            const onClick = useCallback(() => {
                // 3-state cycle: None -> DESC -> ASC -> None (clear/reset to default)
                if (!isSortedByMyField) {
                    // Not currently sorted by this field, start with DESC
                    console.log(`JFBW: Setting sort to DESC for ${orderByField}`)
                    setMarketingAnalyticsOrderBy(orderByField, 'DESC')
                } else if (isDescending) {
                    // Currently DESC, change to ASC
                    console.log(`JFBW: Setting sort to ASC for ${orderByField}`)
                    setMarketingAnalyticsOrderBy(orderByField, 'ASC')
                } else if (isAscending) {
                    // Currently ASC, clear the sort (reset to default order)
                    console.log(`JFBW: Clearing sort for ${orderByField} - resetting to default order`)
                    clearMarketingAnalyticsOrderBy()
                }
            }, [isSortedByMyField, isAscending, isDescending, orderByField])

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
        }

    // Generate dynamic column mappings for conversion goals
    const conversionGoalColumns = useMemo(() => {
        const columns: Record<string, any> = {}
        
        conversion_goals?.forEach((goal, index) => {
            const goalName = goal.conversion_goal_name || `Goal ${index + 1}`
            const costPerGoalName = `Cost per ${goalName}`
            
            // Add conversion count column
            columns[goalName] = {
                renderTitle: MarketingSortableCell(goalName, `cg_${index}.conversion_${index}`),
                render: ({ value }: { value: any }) => value || 0,
                align: 'right',
            }
            
            // Add cost per conversion column
            columns[costPerGoalName] = {
                renderTitle: MarketingSortableCell(costPerGoalName, `cc.total_cost / nullif(cg_${index}.conversion_${index}, 0)`),
                render: ({ value }: { value: any }) => value && typeof value === 'number' ? `$${value.toFixed(2)}` : '-',
                align: 'right',
            }
        })
        
        return columns
    }, [conversion_goals, MarketingSortableCell])

    // Create custom context with sortable headers for marketing analytics
    const marketingAnalyticsContext: QueryContext = {
        ...webAnalyticsDataTableQueryContext,
        insightProps,
        columns: {
            ...webAnalyticsDataTableQueryContext.columns,
            // Add sortable column headers for marketing analytics fields
            // These match the backend output column names
            'Campaign': {
                renderTitle: MarketingSortableCell('Campaign', 'cc.campaign_name'),
            },
            'Source': {
                renderTitle: MarketingSortableCell('Source', 'cc.source_name'),
            },
            'Total Cost': {
                renderTitle: MarketingSortableCell('Total Cost', 'cc.total_cost'),
                render: webAnalyticsDataTableQueryContext.columns?.cost?.render,
                align: 'right',
            },
            'Total Clicks': {
                renderTitle: MarketingSortableCell('Total Clicks', 'cc.total_clicks'),
                render: webAnalyticsDataTableQueryContext.columns?.clicks?.render,
                align: 'right',
            },
            'Total Impressions': {
                renderTitle: MarketingSortableCell('Total Impressions', 'cc.total_impressions'),
                render: webAnalyticsDataTableQueryContext.columns?.impressions?.render,
                align: 'right',
            },
            'Cost per Click': {
                renderTitle: MarketingSortableCell('Cost per Click', 'cc.total_cost / nullif(cc.total_clicks, 0)'),
                render: webAnalyticsDataTableQueryContext.columns?.cpc?.render,
                align: 'right',
            },
            'CTR': {
                renderTitle: MarketingSortableCell('CTR', 'cc.total_clicks / nullif(cc.total_impressions, 0) * 100'),
                render: webAnalyticsDataTableQueryContext.columns?.ctr?.render,
                align: 'right',
            },
            // Add dynamic conversion goal columns
            ...conversionGoalColumns,
        },
    }

    console.log('JFBW: Rendering MarketingAnalyticsTable with:', { 
        query: queryWithOrderBy, 
        orderBy: marketingAnalyticsOrderBy,
        hasOrderBy: queryWithOrderBy.source.kind === 'MarketingAnalyticsTableQuery' && !!queryWithOrderBy.source.orderBy,
        conversionGoalsCount: conversion_goals?.length || 0,
        conversionGoalColumns: Object.keys(conversionGoalColumns)
    })

    return (
        <div className="bg-surface-primary">
            <Query query={queryWithOrderBy} readOnly={false} context={marketingAnalyticsContext} />
        </div>
    )
} 