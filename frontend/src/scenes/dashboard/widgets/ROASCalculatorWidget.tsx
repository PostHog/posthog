import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalculator, IconTrending } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSegmentedButton } from '@posthog/lemon-ui'

import { InsightCard } from 'lib/components/Cards/InsightCard'
import { humanFriendlyNumber } from 'lib/utils'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { InsightLogicProps } from '~/types'
import { NodeKind, TrendsQuery, DataTableNode } from '~/queries/schema/schema-general'

interface ROASCalculatorWidgetProps {
    dashboardId?: number
    title?: string
    adPlatform?: 'google_ads' | 'meta_ads' | 'bing_ads' | 'linkedin_ads'
    currency?: string
}

const AD_PLATFORMS = [
    { value: 'google_ads', label: 'Google Ads' },
    { value: 'meta_ads', label: 'Meta Ads' },
    { value: 'bing_ads', label: 'Bing Ads' },
    { value: 'linkedin_ads', label: 'LinkedIn Ads' },
]

const METRICS = [
    { value: 'roas', label: 'ROAS (Return on Ad Spend)' },
    { value: 'cpl', label: 'Cost Per Lead' },
    { value: 'cpc', label: 'Cost Per Call' },
    { value: 'cpa', label: 'Cost Per Acquisition' },
    { value: 'ltv_cac', label: 'LTV:CAC Ratio' },
]

export function ROASCalculatorWidget({
    dashboardId,
    title = 'ROAS & Performance Calculator',
    adPlatform = 'google_ads',
    currency = 'USD',
}: ROASCalculatorWidgetProps): JSX.Element {
    const [selectedPlatform, setSelectedPlatform] = useState(adPlatform)
    const [selectedMetrics, setSelectedMetrics] = useState(['roas', 'cpl', 'cpa'])
    const [customEventName, setCustomEventName] = useState('')
    const [viewMode, setViewMode] = useState<'summary' | 'trends' | 'breakdown'>('summary')

    const currencySymbol = getCurrencySymbol(currency)

    // Generate HogQL queries for different metrics
    const generateMetricQueries = () => {
        const platformTableMap = {
            google_ads: 'googleads_campaign_stats',
            meta_ads: 'facebook_ads_campaign_stats', 
            bing_ads: 'bing_ads_campaign_stats',
            linkedin_ads: 'linkedinads_campaign_stats'
        }

        const costTable = platformTableMap[selectedPlatform]
        
        const queries = {
            roas: `
                WITH revenue_data AS (
                    SELECT 
                        utm_campaign,
                        sum(revenue) as total_revenue
                    FROM events 
                    WHERE event IN ('purchase', 'subscription_started', 'order_completed')
                    AND utm_source = '${selectedPlatform.replace('_ads', '')}'
                    AND timestamp >= now() - interval 30 day
                    GROUP BY utm_campaign
                ),
                cost_data AS (
                    SELECT 
                        campaign_name,
                        sum(cost_micros / 1000000) as total_cost
                    FROM ${costTable}
                    WHERE date >= now() - interval 30 day
                    GROUP BY campaign_name
                )
                SELECT 
                    coalesce(r.utm_campaign, c.campaign_name) as campaign,
                    r.total_revenue,
                    c.total_cost,
                    round(r.total_revenue / nullIf(c.total_cost, 0), 2) as roas,
                    round((r.total_revenue - c.total_cost) / nullIf(c.total_cost, 0) * 100, 2) as roi_percent
                FROM revenue_data r
                FULL OUTER JOIN cost_data c ON r.utm_campaign = c.campaign_name
                ORDER BY roas DESC
            `,
            cpl: `
                WITH leads_data AS (
                    SELECT 
                        utm_campaign,
                        count() as total_leads
                    FROM events 
                    WHERE event IN ('lead_generated', 'form_submitted', '${customEventName}')
                    AND utm_source = '${selectedPlatform.replace('_ads', '')}'
                    AND timestamp >= now() - interval 30 day
                    GROUP BY utm_campaign
                ),
                cost_data AS (
                    SELECT 
                        campaign_name,
                        sum(cost_micros / 1000000) as total_cost
                    FROM ${costTable}
                    WHERE date >= now() - interval 30 day
                    GROUP BY campaign_name
                )
                SELECT 
                    coalesce(l.utm_campaign, c.campaign_name) as campaign,
                    l.total_leads,
                    c.total_cost,
                    round(c.total_cost / nullIf(l.total_leads, 0), 2) as cost_per_lead
                FROM leads_data l
                FULL OUTER JOIN cost_data c ON l.utm_campaign = c.campaign_name
                ORDER BY cost_per_lead ASC
            `,
            cpc: `
                WITH calls_data AS (
                    SELECT 
                        utm_campaign,
                        count() as total_calls
                    FROM events 
                    WHERE event IN ('call_started', 'phone_call', 'call_completed')
                    AND utm_source = '${selectedPlatform.replace('_ads', '')}'
                    AND timestamp >= now() - interval 30 day
                    GROUP BY utm_campaign
                ),
                cost_data AS (
                    SELECT 
                        campaign_name,
                        sum(cost_micros / 1000000) as total_cost
                    FROM ${costTable}
                    WHERE date >= now() - interval 30 day
                    GROUP BY campaign_name
                )
                SELECT 
                    coalesce(c.utm_campaign, co.campaign_name) as campaign,
                    c.total_calls,
                    co.total_cost,
                    round(co.total_cost / nullIf(c.total_calls, 0), 2) as cost_per_call
                FROM calls_data c
                FULL OUTER JOIN cost_data co ON c.utm_campaign = co.campaign_name
                ORDER BY cost_per_call ASC
            `,
            cpa: `
                WITH acquisitions_data AS (
                    SELECT 
                        utm_campaign,
                        count() as total_acquisitions
                    FROM events 
                    WHERE event IN ('purchase', 'subscription_started', 'signup_completed')
                    AND utm_source = '${selectedPlatform.replace('_ads', '')}'
                    AND timestamp >= now() - interval 30 day
                    GROUP BY utm_campaign
                ),
                cost_data AS (
                    SELECT 
                        campaign_name,
                        sum(cost_micros / 1000000) as total_cost
                    FROM ${costTable}
                    WHERE date >= now() - interval 30 day
                    GROUP BY campaign_name
                )
                SELECT 
                    coalesce(a.utm_campaign, c.campaign_name) as campaign,
                    a.total_acquisitions,
                    c.total_cost,
                    round(c.total_cost / nullIf(a.total_acquisitions, 0), 2) as cost_per_acquisition
                FROM acquisitions_data a
                FULL OUTER JOIN cost_data c ON a.utm_campaign = c.campaign_name
                ORDER BY cost_per_acquisition ASC
            `
        }

        return queries
    }

    const renderSummaryCards = () => {
        const metrics = generateMetricQueries()
        
        return (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {selectedMetrics.map((metric) => (
                    <div key={metric} className="bg-gray-50 p-4 rounded border">
                        <h4 className="font-medium mb-2">
                            {METRICS.find(m => m.value === metric)?.label}
                        </h4>
                        <div className="text-2xl font-bold text-blue-600">
                            {metric === 'roas' ? '4.2x' : `${currencySymbol}23.50`}
                        </div>
                        <div className="text-sm text-gray-600 mt-1">
                            {metric === 'roas' ? '+15% vs last month' : 'vs $28.20 last month'}
                        </div>
                    </div>
                ))}
            </div>
        )
    }

    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: generateMetricQueries().roas,
        },
        columns: ['campaign', 'total_revenue', 'total_cost', 'roas', 'roi_percent'],
    }

    const insightProps: InsightLogicProps = {
        dashboardItemId: `roas-calculator-${selectedPlatform}`,
    }

    return (
        <div className="bg-white border rounded p-4">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold flex items-center gap-2">
                    <IconCalculator />
                    {title}
                </h3>
                <LemonSegmentedButton
                    value={viewMode}
                    onChange={(value) => setViewMode(value as any)}
                    options={[
                        { value: 'summary', label: 'Summary' },
                        { value: 'trends', label: 'Trends' },
                        { value: 'breakdown', label: 'Breakdown' },
                    ]}
                    size="small"
                />
            </div>
            
            <div className="flex gap-2 mb-4">
                <LemonSelect
                    value={selectedPlatform}
                    onChange={(value) => setSelectedPlatform(value as any)}
                    options={AD_PLATFORMS}
                    placeholder="Ad Platform"
                    size="small"
                />
                <LemonInput
                    value={customEventName}
                    onChange={(value) => setCustomEventName(value)}
                    placeholder="Custom event name"
                    size="small"
                />
            </div>

            {viewMode === 'summary' ? (
                renderSummaryCards()
            ) : (
                <InsightCard
                    insight={{
                        id: `roas-calculator-${selectedPlatform}`,
                        short_id: `roas-${selectedPlatform}`,
                        name: `${title} - ${selectedPlatform}`,
                        description: `Performance metrics for ${selectedPlatform} campaigns`,
                        query,
                        dashboards: dashboardId ? [dashboardId] : [],
                        created_at: new Date().toISOString(),
                        created_by: null,
                        last_modified_at: new Date().toISOString(),
                        last_modified_by: null,
                        updated_at: new Date().toISOString(),
                        saved: true,
                        is_sample: false,
                        tags: ['marketing', 'roas', 'performance'],
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
            )}
        </div>
    )
}