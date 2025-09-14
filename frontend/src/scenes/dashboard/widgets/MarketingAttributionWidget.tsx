import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconGraph, IconTrending } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { InsightCard } from 'lib/components/Cards/InsightCard'
import { InsightLogicProps } from '~/types'
import { NodeKind, TrendsQuery, DataTableNode } from '~/queries/schema/schema-general'

interface MarketingAttributionWidgetProps {
    dashboardId?: number
    title?: string
    eventName?: string
    attributionModel?: 'first_touch' | 'last_touch' | 'linear' | 'time_decay'
    conversionWindow?: number
}

const ATTRIBUTION_MODELS = [
    { value: 'first_touch', label: 'First Touch' },
    { value: 'last_touch', label: 'Last Touch' },
    { value: 'linear', label: 'Linear' },
    { value: 'time_decay', label: 'Time Decay' },
]

const CONVERSION_WINDOWS = [
    { value: 1, label: '1 day' },
    { value: 7, label: '7 days' },
    { value: 14, label: '14 days' },
    { value: 30, label: '30 days' },
    { value: 90, label: '90 days' },
]

export function MarketingAttributionWidget({
    dashboardId,
    title = 'Marketing Attribution',
    eventName = 'purchase',
    attributionModel = 'last_touch',
    conversionWindow = 30,
}: MarketingAttributionWidgetProps): JSX.Element {
    const [selectedModel, setSelectedModel] = useState(attributionModel)
    const [selectedWindow, setSelectedWindow] = useState(conversionWindow)
    const [viewMode, setViewMode] = useState<'trends' | 'table'>('trends')

    // Generate the HogQL query for attribution analysis
    const generateAttributionQuery = () => {
        let attributionLogic = ''
        
        switch (selectedModel) {
            case 'first_touch':
                attributionLogic = `
                    SELECT 
                        initial_utm_source,
                        initial_utm_medium,
                        initial_utm_campaign,
                        count() as conversions,
                        sum(revenue) as total_revenue
                    FROM events 
                    WHERE event = '${eventName}' 
                    AND timestamp > now() - interval ${selectedWindow} day
                    GROUP BY initial_utm_source, initial_utm_medium, initial_utm_campaign
                `
                break
            case 'last_touch':
                attributionLogic = `
                    SELECT 
                        utm_source,
                        utm_medium,
                        utm_campaign,
                        count() as conversions,
                        sum(revenue) as total_revenue
                    FROM events 
                    WHERE event = '${eventName}' 
                    AND timestamp > now() - interval ${selectedWindow} day
                    GROUP BY utm_source, utm_medium, utm_campaign
                `
                break
            case 'linear':
                attributionLogic = `
                    WITH attribution_touchpoints AS (
                        SELECT 
                            person_id,
                            utm_source,
                            utm_medium,
                            utm_campaign,
                            timestamp,
                            revenue / countIf(utm_source != '', person_id) as attributed_value
                        FROM events 
                        WHERE timestamp > now() - interval ${selectedWindow} day
                        AND utm_source != ''
                    )
                    SELECT 
                        utm_source,
                        utm_medium,
                        utm_campaign,
                        count() as touchpoints,
                        sum(attributed_value) as attributed_revenue
                    FROM attribution_touchpoints
                    GROUP BY utm_source, utm_medium, utm_campaign
                `
                break
            case 'time_decay':
                attributionLogic = `
                    WITH weighted_attribution AS (
                        SELECT 
                            person_id,
                            utm_source,
                            utm_medium,
                            utm_campaign,
                            revenue * exp(-0.1 * dateDiff('day', timestamp, now())) as time_decayed_value
                        FROM events 
                        WHERE timestamp > now() - interval ${selectedWindow} day
                        AND utm_source != ''
                    )
                    SELECT 
                        utm_source,
                        utm_medium,
                        utm_campaign,
                        count() as touchpoints,
                        sum(time_decayed_value) as attributed_revenue
                    FROM weighted_attribution
                    GROUP BY utm_source, utm_medium, utm_campaign
                `
                break
        }
        
        return attributionLogic
    }

    const query: TrendsQuery | DataTableNode = viewMode === 'trends' 
        ? {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: eventName,
                    name: `${eventName} (${selectedModel})`,
                    math: 'total',
                }
            ],
            trendsFilter: {
                display: 'ActionsLineGraph',
                aggregationAxisFormat: 'numeric',
            },
            breakdownFilter: {
                breakdown: 'utm_source',
                breakdown_type: 'event',
            },
            interval: 'day',
            dateRange: {
                date_from: `-${selectedWindow}d`,
                date_to: null,
            },
        }
        : {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: generateAttributionQuery(),
            },
            columns: [
                'utm_source',
                'utm_medium', 
                'utm_campaign',
                'conversions',
                'total_revenue'
            ],
        }

    const insightProps: InsightLogicProps = {
        dashboardItemId: `marketing-attribution-${selectedModel}-${selectedWindow}`,
    }

    return (
        <div className="bg-white border rounded p-4">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold">{title}</h3>
                <div className="flex gap-2">
                    <LemonSegmentedButton
                        value={viewMode}
                        onChange={(value) => setViewMode(value as 'trends' | 'table')}
                        options={[
                            { value: 'trends', label: 'Trends', icon: <IconGraph /> },
                            { value: 'table', label: 'Table', icon: <IconTrending /> },
                        ]}
                        size="small"
                    />
                </div>
            </div>
            
            <div className="flex gap-2 mb-4">
                <LemonSelect
                    value={selectedModel}
                    onChange={(value) => setSelectedModel(value as any)}
                    options={ATTRIBUTION_MODELS}
                    placeholder="Attribution Model"
                    size="small"
                />
                <LemonSelect
                    value={selectedWindow}
                    onChange={(value) => setSelectedWindow(value as number)}
                    options={CONVERSION_WINDOWS}
                    placeholder="Conversion Window"
                    size="small"
                />
            </div>

            <InsightCard
                insight={{
                    id: Math.random(),
                    short_id: `attr-${Date.now()}`,
                    name: `${title} - ${selectedModel}`,
                    description: `Attribution analysis using ${selectedModel} model with ${selectedWindow} day window`,
                    query,
                    dashboards: dashboardId ? [dashboardId] : [],
                    created_at: new Date().toISOString(),
                    created_by: null,
                    last_modified_at: new Date().toISOString(),
                    last_modified_by: null,
                    updated_at: new Date().toISOString(),
                    saved: true,
                    is_sample: false,
                    tags: ['marketing', 'attribution'],
                    last_refresh: null,
                    next_allowed_client_refresh: null,
                    effective_restriction_level: 21,
                    effective_privilege_level: 37,
                    timezone: null,
                    order: null,
                } as any}
                dashboardId={dashboardId}
                showEditingControls={true}
                showDetailsControls={true}
            />
        </div>
    )
}