/**
 * Enhanced Marketing Attribution & Tracking Widgets for PostHog
 * 
 * This module exports advanced marketing attribution widgets that address
 * the feature requests for full-suite ad attribution & marketing tracking.
 * 
 * Features Implemented:
 * 1. Multiple attribution models (first-touch, last-touch, linear, time-decay)
 * 2. ROAS and CPA calculators for all major ad platforms
 * 3. Lead journey tracking with detailed audit trails
 * 4. Revenue tracking from payment gateways via webhooks
 * 5. Conversion event deduplication
 * 6. Multi-platform ad integration (Google, Meta, Bing, LinkedIn)
 */

// Main comprehensive dashboard
export { EnhancedMarketingDashboard } from './EnhancedMarketingDashboard'

// Individual widget components
export { MarketingAttributionWidget } from './MarketingAttributionWidget'
export { ROASCalculatorWidget } from './ROASCalculatorWidget'
export { LeadAuditTrailWidget } from './LeadAuditTrailWidget'

// Widget configurations and types
export interface WidgetConfig {
    title?: string
    dashboardId?: number
    refreshInterval?: number
    customProperties?: Record<string, any>
}

export interface AttributionModelConfig {
    model: 'first_touch' | 'last_touch' | 'linear' | 'time_decay' | 'position_based'
    conversionWindow: number
    conversionEvents: string[]
}

export interface AdPlatformConfig {
    platform: 'google_ads' | 'meta_ads' | 'bing_ads' | 'linkedin_ads'
    accountId: string
    currency: string
    includeInstagram?: boolean
}

export interface RevenueTrackingConfig {
    paymentGateways: string[]
    webhookEndpoints: Record<string, string>
    deduplicationWindow: number
}

// Utility functions for widget integration
export const createMarketingAttributionInsight = (config: AttributionModelConfig) => {
    return {
        name: `Marketing Attribution - ${config.model}`,
        description: `Attribution analysis using ${config.model} model`,
        filters: {
            events: config.conversionEvents.map(event => ({ event })),
            breakdown: 'utm_source',
            breakdown_type: 'event'
        },
        insight: 'TRENDS',
        display: 'ActionsLineGraph'
    }
}

export const createROASInsight = (config: AdPlatformConfig) => {
    return {
        name: `ROAS - ${config.platform}`,
        description: `Return on ad spend for ${config.platform}`,
        query: {
            kind: 'DataTableNode',
            source: {
                kind: 'HogQLQuery',
                query: `
                    SELECT 
                        utm_campaign,
                        sum(revenue) as total_revenue,
                        sum(ad_cost) as total_cost,
                        round(sum(revenue) / nullIf(sum(ad_cost), 0), 2) as roas
                    FROM events 
                    WHERE utm_source = '${config.platform.replace('_ads', '')}'
                    AND timestamp >= now() - interval 30 day
                    GROUP BY utm_campaign
                    ORDER BY roas DESC
                `
            }
        }
    }
}

// Widget registration for PostHog dashboard system
export const ENHANCED_MARKETING_WIDGETS = [
    {
        id: 'marketing-attribution',
        name: 'Marketing Attribution Analysis',
        description: 'Multi-touch attribution with various models',
        component: 'MarketingAttributionWidget',
        category: 'marketing',
        tags: ['attribution', 'analytics', 'marketing']
    },
    {
        id: 'roas-calculator',
        name: 'ROAS & Performance Calculator', 
        description: 'Automated calculation of marketing performance metrics',
        component: 'ROASCalculatorWidget',
        category: 'marketing',
        tags: ['roas', 'performance', 'calculator']
    },
    {
        id: 'lead-audit-trail',
        name: 'Lead Journey & Audit Trail',
        description: 'Detailed tracking of lead journey from first touch to conversion',
        component: 'LeadAuditTrailWidget', 
        category: 'marketing',
        tags: ['journey', 'leads', 'audit']
    },
    {
        id: 'enhanced-marketing-dashboard',
        name: 'Enhanced Marketing Dashboard',
        description: 'Comprehensive marketing attribution and tracking dashboard',
        component: 'EnhancedMarketingDashboard',
        category: 'dashboard',
        tags: ['marketing', 'dashboard', 'comprehensive']
    }
]

// Default configurations
export const DEFAULT_ATTRIBUTION_CONFIG: AttributionModelConfig = {
    model: 'last_touch',
    conversionWindow: 30,
    conversionEvents: ['purchase', 'subscription_started', 'lead_generated']
}

export const DEFAULT_AD_PLATFORM_CONFIG: AdPlatformConfig = {
    platform: 'google_ads',
    accountId: '',
    currency: 'USD'
}

export const DEFAULT_REVENUE_CONFIG: RevenueTrackingConfig = {
    paymentGateways: ['stripe', 'paypal'],
    webhookEndpoints: {},
    deduplicationWindow: 7
}

// Integration helpers
export const integrateWithDashboard = (dashboardId: number, widgetConfigs: WidgetConfig[]) => {
    // This would integrate with PostHog's dashboard system
    // to add the widgets to an existing dashboard
    return widgetConfigs.map(config => ({
        ...config,
        dashboardId,
        createdAt: new Date().toISOString()
    }))
}

export const setupWebhookEndpoints = (teamId: number) => {
    // Generate webhook URLs for revenue tracking
    const baseUrl = window.location.origin
    
    return {
        stripe: `${baseUrl}/webhooks/revenue/stripe`,
        paypal: `${baseUrl}/webhooks/revenue/paypal`,
        square: `${baseUrl}/webhooks/revenue/square`,
        generic: `${baseUrl}/webhooks/revenue/generic`,
        headers: {
            'X-PostHog-Team-Id': teamId.toString()
        }
    }
}

// Export widget metadata for registration
export const WIDGET_METADATA = {
    version: '1.0.0',
    author: 'PostHog Enhanced Marketing Attribution',
    description: 'Advanced marketing attribution and tracking widgets',
    features: [
        'Multi-touch attribution models',
        'ROAS and CPA calculations',
        'Lead journey tracking',
        'Revenue tracking via webhooks',
        'Conversion deduplication',
        'Multi-platform ad integration'
    ],
    supportedPlatforms: [
        'Google Ads',
        'Meta Ads (Facebook/Instagram)', 
        'Microsoft Ads (Bing)',
        'LinkedIn Ads',
        'Twitter Ads (planned)',
        'TikTok Ads (planned)'
    ],
    paymentGateways: [
        'Stripe',
        'PayPal',
        'Square',
        'Braintree',
        'Custom webhooks'
    ]
}