import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDashboard, IconPlus, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { InsightCard } from 'lib/components/Cards/InsightCard'
import { InsightLogicProps } from '~/types'
import { NodeKind, TrendsQuery, DataTableNode } from '~/queries/schema/schema-general'

// Import our new widgets
import { MarketingAttributionWidget } from './MarketingAttributionWidget'
import { ROASCalculatorWidget } from './ROASCalculatorWidget'
import { LeadAuditTrailWidget } from './LeadAuditTrailWidget'

interface EnhancedMarketingDashboardProps {
    dashboardId?: number
    title?: string
}

const WIDGET_TYPES = [
    { 
        value: 'attribution', 
        label: 'Marketing Attribution', 
        description: 'Multi-touch attribution analysis with various models'
    },
    { 
        value: 'roas', 
        label: 'ROAS & Performance Calculator', 
        description: 'Automated calculation of ROAS, Cost Per Lead, Cost Per Call'
    },
    { 
        value: 'journey', 
        label: 'Lead Journey & Audit Trail', 
        description: 'Detailed lead tracking from first touch to conversion'
    },
    {
        value: 'revenue_tracking',
        label: 'Revenue Tracking',
        description: 'Track revenue from multiple payment gateways via webhooks'
    },
    {
        value: 'conversion_dedup',
        label: 'Conversion Deduplication',
        description: 'Prevent double-counting of conversion events'
    },
    {
        value: 'ad_platform_integration',
        label: 'Multi-Platform Ad Integration',
        description: 'Connect Google Ads, Meta Ads, Bing Ads, LinkedIn Ads'
    }
]

const AD_PLATFORMS = [
    { value: 'google_ads', label: 'Google Ads', status: 'active' },
    { value: 'meta_ads', label: 'Meta Ads (Facebook/Instagram)', status: 'active' },
    { value: 'bing_ads', label: 'Microsoft Ads (Bing)', status: 'beta' },
    { value: 'linkedin_ads', label: 'LinkedIn Ads', status: 'active' },
    { value: 'twitter_ads', label: 'Twitter Ads', status: 'planned' },
    { value: 'tiktok_ads', label: 'TikTok Ads', status: 'planned' },
]

export function EnhancedMarketingDashboard({
    dashboardId,
    title = 'Enhanced Marketing Attribution Dashboard',
}: EnhancedMarketingDashboardProps): JSX.Element {
    const [activeWidgets, setActiveWidgets] = useState(['attribution', 'roas', 'journey'])
    const [showAddWidget, setShowAddWidget] = useState(false)
    const [connectedPlatforms, setConnectedPlatforms] = useState(['google_ads', 'meta_ads'])

    // Revenue Tracking Widget Component
    const RevenueTrackingWidget = () => (
        <div className="bg-white border rounded p-4">
            <h3 className="text-lg font-semibold mb-4">Revenue Tracking Setup</h3>
            <div className="space-y-3">
                <div className="bg-blue-50 p-3 rounded">
                    <h4 className="font-medium text-blue-900">Payment Gateway Webhooks</h4>
                    <p className="text-sm text-blue-700 mt-1">
                        Configure webhooks from Stripe, PayPal, Square, and other payment processors
                    </p>
                    <LemonButton type="primary" size="small" className="mt-2">
                        Configure Webhooks
                    </LemonButton>
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="bg-green-50 p-2 rounded text-center">
                        <div className="text-xl font-bold text-green-700">$124,583</div>
                        <div className="text-sm text-green-600">Total Revenue (30d)</div>
                    </div>
                    <div className="bg-purple-50 p-2 rounded text-center">
                        <div className="text-xl font-bold text-purple-700">847</div>
                        <div className="text-sm text-purple-600">Transactions (30d)</div>
                    </div>
                </div>
            </div>
        </div>
    )

    // Conversion Deduplication Widget Component
    const ConversionDedupWidget = () => (
        <div className="bg-white border rounded p-4">
            <h3 className="text-lg font-semibold mb-4">Conversion Deduplication</h3>
            <div className="space-y-3">
                <div className="bg-orange-50 p-3 rounded">
                    <h4 className="font-medium text-orange-900">Duplicate Detection Rules</h4>
                    <p className="text-sm text-orange-700 mt-1">
                        Automatically detect and merge duplicate conversion events
                    </p>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="bg-gray-50 p-2 rounded">
                        <div className="text-lg font-bold">234</div>
                        <div className="text-xs text-gray-600">Raw Events</div>
                    </div>
                    <div className="bg-red-50 p-2 rounded">
                        <div className="text-lg font-bold text-red-600">28</div>
                        <div className="text-xs text-gray-600">Duplicates</div>
                    </div>
                    <div className="bg-green-50 p-2 rounded">
                        <div className="text-lg font-bold text-green-600">206</div>
                        <div className="text-xs text-gray-600">Clean Events</div>
                    </div>
                </div>
                <LemonButton type="secondary" size="small" fullWidth>
                    Configure Dedup Rules
                </LemonButton>
            </div>
        </div>
    )

    // Ad Platform Integration Widget Component
    const AdPlatformIntegrationWidget = () => (
        <div className="bg-white border rounded p-4">
            <h3 className="text-lg font-semibold mb-4">Ad Platform Integrations</h3>
            <div className="space-y-2">
                {AD_PLATFORMS.map(platform => (
                    <div key={platform.value} className="flex items-center justify-between p-2 border rounded">
                        <div className="flex items-center gap-2">
                            <div className={`w-3 h-3 rounded-full ${
                                connectedPlatforms.includes(platform.value) 
                                    ? 'bg-green-500' 
                                    : platform.status === 'planned' 
                                    ? 'bg-gray-400' 
                                    : 'bg-yellow-500'
                            }`} />
                            <span className="text-sm font-medium">{platform.label}</span>
                            <span className={`text-xs px-2 py-1 rounded ${
                                platform.status === 'active' ? 'bg-green-100 text-green-800' :
                                platform.status === 'beta' ? 'bg-yellow-100 text-yellow-800' :
                                'bg-gray-100 text-gray-600'
                            }`}>
                                {platform.status}
                            </span>
                        </div>
                        <LemonButton 
                            size="small" 
                            type={connectedPlatforms.includes(platform.value) ? 'secondary' : 'primary'}
                            disabled={platform.status === 'planned'}
                        >
                            {connectedPlatforms.includes(platform.value) ? 'Connected' : 'Connect'}
                        </LemonButton>
                    </div>
                ))}
            </div>
        </div>
    )

    const renderWidget = (widgetType: string) => {
        switch (widgetType) {
            case 'attribution':
                return <MarketingAttributionWidget key="attribution" dashboardId={dashboardId} />
            case 'roas':
                return <ROASCalculatorWidget key="roas" dashboardId={dashboardId} />
            case 'journey':
                return <LeadAuditTrailWidget key="journey" dashboardId={dashboardId} />
            case 'revenue_tracking':
                return <RevenueTrackingWidget key="revenue" />
            case 'conversion_dedup':
                return <ConversionDedupWidget key="dedup" />
            case 'ad_platform_integration':
                return <AdPlatformIntegrationWidget key="platforms" />
            default:
                return null
        }
    }

    const addWidget = (widgetType: string) => {
        if (!activeWidgets.includes(widgetType)) {
            setActiveWidgets([...activeWidgets, widgetType])
        }
        setShowAddWidget(false)
    }

    const removeWidget = (widgetType: string) => {
        setActiveWidgets(activeWidgets.filter(w => w !== widgetType))
    }

    return (
        <div className="space-y-6">
            {/* Dashboard Header */}
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-2xl font-bold flex items-center gap-2">
                        <IconDashboard />
                        {title}
                    </h1>
                    <p className="text-gray-600 mt-1">
                        Comprehensive marketing attribution and ad performance tracking dashboard
                    </p>
                </div>
                <div className="flex gap-2">
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={() => window.location.reload()}
                    >
                        Refresh All
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        onClick={() => setShowAddWidget(true)}
                    >
                        Add Widget
                    </LemonButton>
                </div>
            </div>

            {/* Platform Integration Status */}
            <div className="bg-blue-50 border border-blue-200 rounded p-4">
                <h3 className="font-medium text-blue-900 mb-2">Connected Ad Platforms</h3>
                <div className="flex gap-4">
                    {connectedPlatforms.map(platform => (
                        <div key={platform} className="flex items-center gap-2">
                            <div className="w-2 h-2 bg-green-500 rounded-full" />
                            <span className="text-sm text-blue-800">
                                {AD_PLATFORMS.find(p => p.value === platform)?.label}
                            </span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Widgets Grid */}
            <div className="space-y-6">
                {activeWidgets.map(widgetType => (
                    <div key={widgetType} className="relative">
                        <button
                            onClick={() => removeWidget(widgetType)}
                            className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 text-white rounded-full text-xs z-10 hover:bg-red-600"
                        >
                            ×
                        </button>
                        {renderWidget(widgetType)}
                    </div>
                ))}
            </div>

            {/* Add Widget Modal */}
            <LemonModal
                isOpen={showAddWidget}
                onClose={() => setShowAddWidget(false)}
                title="Add Marketing Widget"
                width={600}
            >
                <div className="space-y-4">
                    <p className="text-gray-600">
                        Choose a widget to add to your marketing attribution dashboard:
                    </p>
                    <div className="space-y-2">
                        {WIDGET_TYPES.filter(w => !activeWidgets.includes(w.value)).map(widget => (
                            <div 
                                key={widget.value}
                                className="border rounded p-3 hover:bg-gray-50 cursor-pointer"
                                onClick={() => addWidget(widget.value)}
                            >
                                <h4 className="font-medium">{widget.label}</h4>
                                <p className="text-sm text-gray-600 mt-1">{widget.description}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </LemonModal>
        </div>
    )
}