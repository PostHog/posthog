import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTarget, IconPath, IconGraph } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { InsightCard } from 'lib/components/Cards/InsightCard'
import { humanFriendlyDuration } from 'lib/utils'
import { InsightLogicProps } from '~/types'
import { NodeKind, FunnelsQuery, PathsQuery, DataTableNode } from '~/queries/schema/schema-general'

interface LeadAuditTrailWidgetProps {
    dashboardId?: number
    title?: string
    leadIdentifier?: string
    conversionEvents?: string[]
}

const DEFAULT_CONVERSION_EVENTS = [
    'lead_generated',
    'form_submitted', 
    'call_started',
    'meeting_booked',
    'purchase',
    'subscription_started'
]

const JOURNEY_VIEWS = [
    { value: 'funnel', label: 'Conversion Funnel', icon: <IconTarget /> },
    { value: 'paths', label: 'User Paths', icon: <IconPath /> },
    { value: 'timeline', label: 'Event Timeline', icon: <IconGraph /> },
]

export function LeadAuditTrailWidget({
    dashboardId,
    title = 'Lead Journey & Attribution Trail',
    leadIdentifier,
    conversionEvents = DEFAULT_CONVERSION_EVENTS,
}: LeadAuditTrailWidgetProps): JSX.Element {
    const [selectedView, setSelectedView] = useState<'funnel' | 'paths' | 'timeline'>('funnel')
    const [selectedLead, setSelectedLead] = useState(leadIdentifier || '')
    const [timeRange, setTimeRange] = useState('30d')

    // Generate journey analysis queries
    const generateJourneyQuery = () => {
        switch (selectedView) {
            case 'funnel':
                return {
                    kind: NodeKind.FunnelsQuery,
                    series: conversionEvents.map((event, index) => ({
                        kind: NodeKind.EventsNode,
                        event,
                        name: event.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase()),
                        order: index,
                    })),
                    funnelsFilter: {
                        funnelWindowInterval: 30,
                        funnelWindowIntervalUnit: 'day',
                        breakdown: 'utm_source',
                        breakdownAttributionType: 'first_touch',
                    },
                    dateRange: {
                        date_from: `-${timeRange}`,
                        date_to: null,
                    },
                } as FunnelsQuery

            case 'paths':
                return {
                    kind: NodeKind.PathsQuery,
                    pathsFilter: {
                        includeEventTypes: ['$pageview', 'custom_event'],
                        startPoint: '$pageview',
                        endPoint: 'purchase',
                        pathGroupings: ['utm_source', 'utm_campaign'],
                        maxEdgeWeight: 20,
                        minEdgeWeight: 1,
                    },
                    dateRange: {
                        date_from: `-${timeRange}`,
                        date_to: null,
                    },
                } as PathsQuery

            case 'timeline':
                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            WITH lead_events AS (
                                SELECT 
                                    person_id,
                                    event,
                                    timestamp,
                                    properties.utm_source as utm_source,
                                    properties.utm_medium as utm_medium,
                                    properties.utm_campaign as utm_campaign,
                                    properties.gclid as google_click_id,
                                    properties.fbclid as facebook_click_id,
                                    properties.$current_url as page_url,
                                    properties.$referrer as referrer,
                                    properties.revenue as revenue,
                                    row_number() OVER (PARTITION BY person_id ORDER BY timestamp) as step_number,
                                    dateDiff('minute', 
                                        first_value(timestamp) OVER (PARTITION BY person_id ORDER BY timestamp), 
                                        timestamp
                                    ) as minutes_from_first_touch
                                FROM events 
                                WHERE ${selectedLead ? `person_id = '${selectedLead}' AND` : ''}
                                timestamp >= now() - interval ${timeRange.replace('d', '')} day
                                AND (
                                    event IN (${conversionEvents.map(e => `'${e}'`).join(',')})
                                    OR event = '$pageview'
                                    OR utm_source IS NOT NULL
                                )
                            )
                            SELECT 
                                person_id,
                                step_number,
                                event,
                                timestamp,
                                utm_source,
                                utm_medium,
                                utm_campaign,
                                page_url,
                                referrer,
                                revenue,
                                minutes_from_first_touch,
                                CASE 
                                    WHEN step_number = 1 THEN 'First Touch'
                                    WHEN event IN (${conversionEvents.map(e => `'${e}'`).join(',')}) THEN 'Conversion Event'
                                    WHEN utm_source IS NOT NULL THEN 'Marketing Touch'
                                    ELSE 'Organic Touch'
                                END as touch_type
                            FROM lead_events
                            ORDER BY person_id, timestamp
                        `,
                    },
                    columns: [
                        'person_id',
                        'step_number', 
                        'event',
                        'timestamp',
                        'touch_type',
                        'utm_source',
                        'utm_campaign',
                        'minutes_from_first_touch',
                        'revenue'
                    ],
                } as DataTableNode
        }
    }

    const renderJourneyInsights = () => {
        return (
            <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="bg-blue-50 p-3 rounded border">
                        <div className="text-sm text-blue-600 font-medium">Avg. Journey Length</div>
                        <div className="text-xl font-bold">7.2 touchpoints</div>
                        <div className="text-xs text-gray-600">+12% vs previous period</div>
                    </div>
                    <div className="bg-green-50 p-3 rounded border">
                        <div className="text-sm text-green-600 font-medium">Time to Conversion</div>
                        <div className="text-xl font-bold">4.5 days</div>
                        <div className="text-xs text-gray-600">-8% vs previous period</div>
                    </div>
                    <div className="bg-purple-50 p-3 rounded border">
                        <div className="text-sm text-purple-600 font-medium">Multi-touch Attribution</div>
                        <div className="text-xl font-bold">68%</div>
                        <div className="text-xs text-gray-600">of conversions</div>
                    </div>
                </div>

                {selectedView === 'timeline' && (
                    <div className="bg-gray-50 p-4 rounded">
                        <h4 className="font-medium mb-3">Sample Lead Journey</h4>
                        <div className="space-y-2">
                            <div className="flex items-center gap-3">
                                <LemonTag type="primary" size="small">First Touch</LemonTag>
                                <span className="text-sm">Google Ads → Landing Page Visit</span>
                                <span className="text-xs text-gray-500">0 min</span>
                            </div>
                            <div className="flex items-center gap-3">
                                <LemonTag type="default" size="small">Touch 2</LemonTag>
                                <span className="text-sm">Direct → Pricing Page Visit</span>
                                <span className="text-xs text-gray-500">2 hours</span>
                            </div>
                            <div className="flex items-center gap-3">
                                <LemonTag type="default" size="small">Touch 3</LemonTag>
                                <span className="text-sm">Email → Product Demo Request</span>
                                <span className="text-xs text-gray-500">1 day</span>
                            </div>
                            <div className="flex items-center gap-3">
                                <LemonTag type="success" size="small">Conversion</LemonTag>
                                <span className="text-sm">Direct → Purchase Completed</span>
                                <span className="text-xs text-gray-500">4 days</span>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        )
    }

    const query = generateJourneyQuery()
    const insightProps: InsightLogicProps = {
        dashboardItemId: `lead-journey-${selectedView}`,
    }

    return (
        <div className="bg-white border rounded p-4">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold flex items-center gap-2">
                    <IconTarget />
                    {title}
                </h3>
                <div className="flex gap-2">
                    {JOURNEY_VIEWS.map(view => (
                        <LemonButton
                            key={view.value}
                            type={selectedView === view.value ? 'primary' : 'tertiary'}
                            size="small"
                            icon={view.icon}
                            onClick={() => setSelectedView(view.value as any)}
                        >
                            {view.label}
                        </LemonButton>
                    ))}
                </div>
            </div>
            
            <div className="flex gap-2 mb-4">
                <LemonSelect
                    value={timeRange}
                    onChange={(value) => setTimeRange(value as string)}
                    options={[
                        { value: '7d', label: 'Last 7 days' },
                        { value: '30d', label: 'Last 30 days' },
                        { value: '90d', label: 'Last 90 days' },
                        { value: '180d', label: 'Last 6 months' },
                    ]}
                    size="small"
                />
                                <LemonInput
                    placeholder="Lead ID (optional)"
                    value={selectedLead}
                    onChange={(value: string) => setSelectedLead(value)}
                    size="small"
                />
            </div>

            {renderJourneyInsights()}

            <div className="mt-4">
                <InsightCard
                    insight={{
                        id: `lead-journey-${selectedView}-${timeRange}`,
                        short_id: `journey-${selectedView}-${timeRange}`,
                        name: `${title} - ${selectedView}`,
                        description: `Lead journey analysis using ${selectedView} view`,
                        query,
                        dashboards: dashboardId ? [dashboardId] : [],
                        created_at: new Date().toISOString(),
                        created_by: null,
                        last_modified_at: new Date().toISOString(),
                        last_modified_by: null,
                        updated_at: new Date().toISOString(),
                        saved: true,
                        is_sample: false,
                        tags: ['marketing', 'journey', 'attribution'],
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
        </div>
    )
}