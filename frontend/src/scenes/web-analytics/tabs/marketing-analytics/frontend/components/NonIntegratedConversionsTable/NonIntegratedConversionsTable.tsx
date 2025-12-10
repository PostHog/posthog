import '../MarketingAnalyticsTable/MarketingAnalyticsTableStyleOverride.scss'

import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { LearnMorePopover } from 'scenes/web-analytics/WebAnalyticsDashboard'

import { Query } from '~/queries/Query/Query'
import { ColumnFeature } from '~/queries/nodes/DataTable/DataTable'
import {
    DataTableNode,
    NodeKind,
    NonIntegratedConversionsColumnsSchemaNames,
    NonIntegratedConversionsTableQuery,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'
import { webAnalyticsDataTableQueryContext } from '~/scenes/web-analytics/tiles/WebAnalyticsTile'
import { InsightLogicProps } from '~/types'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { MarketingAnalyticsCell } from '../../shared'
import { IntegrationSettingsModal } from '../settings/IntegrationSettingsModal'

// Unique ID counter for this component
let uniqueNodeId = 0

const TILE_TITLE = 'Non-integrated conversions'
const TILE_DESCRIPTION =
    'Conversions with UTM parameters set that do not match any campaign data from your integrations. Use the cell actions to map these to your integrations or configure them from the marketing settings. You need to have conversion goals configured to be able to see any data. If you do not see anything, it means all your conversion from the period are mapped to a native source.'

export const NonIntegratedConversionsTable = (): JSX.Element | null => {
    const { conversion_goals, integrationSettingsModal } = useValues(marketingAnalyticsSettingsLogic)
    const { closeIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)
    const { dateFilter, compareFilter, loading, draftConversionGoal } = useValues(marketingAnalyticsLogic)

    // Create a unique, stable insightProps for this component instance
    // Use the shared data node collection ID so global refresh works
    const [uniqueKey] = useState(() => `non-integrated-conversions-${uniqueNodeId++}`)
    const insightProps: InsightLogicProps = useMemo(
        () => ({
            dashboardItemId: `new-${uniqueKey}`,
            dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
        }),
        [uniqueKey]
    )

    // Memoize date values to avoid unnecessary re-renders
    const dateFrom = dateFilter.dateFrom
    const dateTo = dateFilter.dateTo

    // Combine saved conversion goals with draft conversion goal
    const allConversionGoals = useMemo(() => {
        const goals = [...conversion_goals]
        if (draftConversionGoal) {
            goals.push(draftConversionGoal)
        }
        return goals
    }, [conversion_goals, draftConversionGoal])

    // Build columns: Source, Campaign, and conversion goal columns
    const selectColumns = useMemo(() => {
        const baseColumns = [
            NonIntegratedConversionsColumnsSchemaNames.Source,
            NonIntegratedConversionsColumnsSchemaNames.Campaign,
        ]

        // Add conversion goal columns (including draft if present)
        const conversionGoalColumns = allConversionGoals.map((goal) => goal.conversion_goal_name)

        return [...baseColumns, ...conversionGoalColumns]
    }, [allConversionGoals])

    // Build the query - only rebuild when actual values change
    // Show data if there are any conversion goals (saved or draft)
    const query: DataTableNode | null = useMemo(() => {
        if (allConversionGoals.length === 0) {
            return null
        }

        const sourceQuery: NonIntegratedConversionsTableQuery = {
            kind: NodeKind.NonIntegratedConversionsTableQuery,
            dateRange: {
                date_from: dateFrom,
                date_to: dateTo,
            },
            properties: [],
            compareFilter: compareFilter || undefined,
            select: selectColumns,
            limit: 50,
            draftConversionGoal: draftConversionGoal || undefined,
        }

        return {
            kind: NodeKind.DataTableNode,
            source: sourceQuery,
            full: true,
            embedded: false,
            showOpenEditorButton: false,
            showReload: true,
            showExport: true,
        }
    }, [allConversionGoals.length, dateFrom, dateTo, compareFilter, selectColumns, draftConversionGoal])

    // Build context - cell actions are handled directly in DataTable via QueryFeature
    const nonIntegratedContext: QueryContext = useMemo(() => {
        const campaignColumnName = NonIntegratedConversionsColumnsSchemaNames.Campaign

        return {
            ...webAnalyticsDataTableQueryContext,
            insightProps,
            columnFeatures: [ColumnFeature.canSort],
            columns: selectColumns.reduce(
                (acc, column) => {
                    const isCampaignColumn = column === campaignColumnName

                    acc[column] = {
                        title: column,
                        render: (props) => (
                            <MarketingAnalyticsCell
                                {...props}
                                style={{
                                    maxWidth: isCampaignColumn ? '200px' : undefined,
                                }}
                            />
                        ),
                    }
                    return acc
                },
                {} as Record<string, QueryContextColumn>
            ),
        }
    }, [insightProps, selectColumns])

    const TileHeader = (
        <div className="flex flex-row items-center mb-3">
            <h2>{TILE_TITLE}</h2>
            <LearnMorePopover title={TILE_TITLE} description={TILE_DESCRIPTION} />
        </div>
    )

    // Show empty state when no conversion goals are configured (neither saved nor draft)
    if (allConversionGoals.length === 0) {
        return (
            <div className="col-span-1 row-span-1 flex flex-col md:col-span-2 xxl:order-3">
                {TileHeader}
                <div className="p-8 flex flex-col items-center justify-center text-center gap-3 border rounded">
                    <p className="text-muted m-0">No conversion goals configured</p>
                    <p className="text-xs text-muted m-0">
                        Use the "Explore conversion goals" section above, or configure them in settings.
                    </p>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.settings('environment-marketing-analytics')}
                        targetBlank
                        sideIcon={<IconExternal />}
                    >
                        Configure conversion goals
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (loading || !query) {
        return (
            <div className="col-span-1 row-span-1 flex flex-col md:col-span-2 xxl:order-3">
                {TileHeader}
                <div className="p-4">
                    <LemonSkeleton className="h-32" />
                </div>
            </div>
        )
    }

    return (
        <div className="col-span-1 row-span-1 flex flex-col md:col-span-2 xxl:order-3">
            {TileHeader}
            <div className="bg-surface-primary rounded border border-border marketing-analytics-table-container">
                <Query query={query} readOnly={false} context={nonIntegratedContext} />
            </div>
            {integrationSettingsModal.integration && (
                <IntegrationSettingsModal
                    integrationName={integrationSettingsModal.integration}
                    isOpen={integrationSettingsModal.isOpen}
                    onClose={closeIntegrationSettingsModal}
                    initialTab={integrationSettingsModal.initialTab}
                    initialUtmValue={integrationSettingsModal.initialUtmValue}
                />
            )}
        </div>
    )
}
