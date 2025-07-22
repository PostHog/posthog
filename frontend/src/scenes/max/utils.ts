import { decodeParams, encodeParams } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'
import { BillingUsageResponse } from 'scenes/billing/billingUsageLogic'
import { isAddonVisible } from 'scenes/billing/utils'
import { Destination } from 'scenes/pipeline/types'

import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RootAssistantMessage,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from '~/queries/schema/schema-assistant-queries'
import { FunnelsQuery, HogQLQuery, RetentionQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isHogQLQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import {
    ActionType,
    BillingType,
    DashboardType,
    EventDefinition,
    QueryBasedInsightModel,
    SidePanelTab,
    TeamType,
} from '~/types'
import { MaxActionContext, MaxContextType, MaxDashboardContext, MaxEventContext, MaxInsightContext } from './maxTypes'

import { MaxAddonInfo, MaxBillingContext, MaxProductInfo } from './maxTypes'

export function isReasoningMessage(message: RootAssistantMessage | undefined | null): message is ReasoningMessage {
    return message?.type === AssistantMessageType.Reasoning
}

export function isVisualizationMessage(
    message: RootAssistantMessage | undefined | null
): message is VisualizationMessage {
    return message?.type === AssistantMessageType.Visualization
}

export function isHumanMessage(message: RootAssistantMessage | undefined | null): message is HumanMessage {
    return message?.type === AssistantMessageType.Human
}

export function isAssistantMessage(message: RootAssistantMessage | undefined | null): message is AssistantMessage {
    return message?.type === AssistantMessageType.Assistant
}

export function isAssistantToolCallMessage(
    message: RootAssistantMessage | undefined | null
): message is AssistantToolCallMessage & Required<Pick<AssistantToolCallMessage, 'ui_payload'>> {
    return message?.type === AssistantMessageType.ToolCall && message.ui_payload !== undefined
}

export function isFailureMessage(message: RootAssistantMessage | undefined | null): message is FailureMessage {
    return message?.type === AssistantMessageType.Failure
}

// The cast function below look like no-ops, but they're here to ensure AssistantFooQuery types stay compatible
// with their respective FooQuery types. If an incompatibility arises, TypeScript will shout here
function castAssistantTrendsQuery(query: AssistantTrendsQuery): TrendsQuery {
    return query
}
function castAssistantFunnelsQuery(query: AssistantFunnelsQuery): FunnelsQuery {
    return query
}
function castAssistantRetentionQuery(query: AssistantRetentionQuery): RetentionQuery {
    return query
}
function castAssistantHogQLQuery(query: AssistantHogQLQuery): HogQLQuery {
    return query
}
export function castAssistantQuery(
    query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
): TrendsQuery | FunnelsQuery | RetentionQuery | HogQLQuery {
    if (isTrendsQuery(query)) {
        return castAssistantTrendsQuery(query)
    } else if (isFunnelsQuery(query)) {
        return castAssistantFunnelsQuery(query)
    } else if (isRetentionQuery(query)) {
        return castAssistantRetentionQuery(query)
    } else if (isHogQLQuery(query)) {
        return castAssistantHogQLQuery(query)
    }
    throw new Error(`Unsupported query type: ${query.kind}`)
}

/**
 * Generate a URL for a conversation.
 */
export function getConversationUrl({
    pathname,
    search,
    conversationId,
    includeHash = true,
}: {
    pathname: string
    search: string
    conversationId: string
    includeHash?: boolean
}): string {
    const params = decodeParams(search, '?')
    const strParams = encodeParams({
        ...params,
        chat: conversationId,
    })
    return `${pathname}${strParams ? `?${strParams}` : ''}${includeHash ? `#panel=${SidePanelTab.Max}` : ''}`
}

export function formatConversationDate(updatedAt: string | null): string {
    if (!updatedAt) {
        return 'Some time ago'
    }

    const diff = dayjs().diff(dayjs(updatedAt), 'seconds')
    if (diff < 60) {
        return 'Just now'
    }
    return humanFriendlyDuration(diff, { maxUnits: 1 })
}

/**
 * Checks if a suggestion requires user input.
 * @param suggestion - The suggestion to check.
 * @returns True if the suggestion requires input, false otherwise.
 */
export function checkSuggestionRequiresUserInput(suggestion: string): boolean {
    const matches = suggestion.match(/<|>|…/g)
    return !!matches && matches.length > 0
}

/**
 * Strips the user input placeholder (`<`, `>`, `…`) from a suggestion.
 * @param suggestion - The suggestion to strip.
 * @returns The stripped suggestion.
 */
export function stripSuggestionPlaceholders(suggestion: string): string {
    return `${suggestion
        .replace(/<[^>]*>/g, '')
        .replace(/…$/, '')
        .trim()} `
}

/**
 * Formats a suggestion by stripping the placeholder characters (`<`, `>`) from a suggestion.
 * @param suggestion - The suggestion to format.
 * @returns The formatted suggestion.
 */
export function formatSuggestion(suggestion: string): string {
    return `${suggestion.replace(/[<>]/g, '').replace(/…$/, '').trim()}${suggestion.endsWith('…') ? '…' : ''}`
}

export function generateBurstPoints(spikeCount: number, spikiness: number): string {
    if (spikiness < 0 || spikiness > 1) {
        throw new Error('Spikiness must be between 0 and 1')
    }
    if (spikeCount < 1) {
        throw new Error('Spikes must be at least 1')
    }

    let points = ''
    const outerRadius = 50
    const innerRadius = 50 * (1 - spikiness)

    for (let i = 0; i < spikeCount * 2; i++) {
        const radius = i % 2 === 0 ? outerRadius : innerRadius
        const angle = (Math.PI * i) / spikeCount
        const x = 50 + radius * Math.cos(angle)
        const y = 50 + radius * Math.sin(angle)
        points += `${x},${y} `
    }

    return points.trim()
}

// Utility functions for transforming data to max context
export const insightToMaxContext = (insight: Partial<QueryBasedInsightModel>): MaxInsightContext => {
    const source = (insight.query as any)?.source
    return {
        type: MaxContextType.INSIGHT,
        id: insight.short_id!,
        name: insight.name || insight.derived_name,
        description: insight.description,
        query: source,
    }
}

export const dashboardToMaxContext = (dashboard: DashboardType<QueryBasedInsightModel>): MaxDashboardContext => {
    return {
        type: MaxContextType.DASHBOARD,
        id: dashboard.id,
        name: dashboard.name,
        description: dashboard.description,
        insights: dashboard.tiles.filter((tile) => tile.insight).map((tile) => insightToMaxContext(tile.insight!)),
        filters: dashboard.filters,
    }
}

export const eventToMaxContextPayload = (event: EventDefinition): MaxEventContext => {
    return {
        type: MaxContextType.EVENT,
        id: event.id,
        name: event.name,
        description: event.description,
    }
}

export const actionToMaxContextPayload = (action: ActionType): MaxActionContext => {
    return {
        type: MaxContextType.ACTION,
        id: action.id,
        name: action.name || `Action ${action.id}`,
        description: action.description || '',
    }
}

export const billingToMaxContext = (
    billing: BillingType | null,
    featureFlags: Record<string, any>,
    currentTeam: TeamType,
    destinations: Destination[],
    usageResponse?: BillingUsageResponse
): MaxBillingContext | null => {
    if (!billing) {
        return null
    }

    // Helper function to get custom limit for a product
    const getCustomLimitForProduct = (productType: string, usageKey?: string): number | null => {
        if (!billing.custom_limits_usd) {
            return null
        }

        // First try product type, then fallback to usage key
        const customLimit = billing.custom_limits_usd[productType]
        if (customLimit === 0 || customLimit) {
            return customLimit
        }

        return usageKey ? billing.custom_limits_usd[usageKey] ?? null : null
    }
    const getNextPeriodCustomLimitForProduct = (productType: string, usageKey?: string): number | null => {
        if (!billing.next_period_custom_limits_usd) {
            return null
        }

        const customLimit = billing.next_period_custom_limits_usd[productType]
        if (customLimit === 0 || customLimit) {
            return customLimit
        }

        return usageKey ? billing.next_period_custom_limits_usd[usageKey] ?? null : null
    }

    // Filter platform products to only include the highest tier available
    const processedProducts = (billing.products || []).map((product) => {
        if (product.type === 'platform_and_support') {
            const availablePlans = product.plans || []
            const currentPlanIndex = availablePlans.findIndex((plan) => plan.current_plan)
            const highestAvailablePlan =
                currentPlanIndex >= 0 ? availablePlans[currentPlanIndex] : availablePlans[availablePlans.length - 1] // Fallback to highest plan

            if (highestAvailablePlan) {
                return {
                    ...product,
                    name: `${product.name} (${highestAvailablePlan.name})`,
                    description: highestAvailablePlan.description || product.description,
                }
            }
        }
        return product
    })

    const maxProducts: MaxProductInfo[] = processedProducts.map((product) => {
        const customLimit = getCustomLimitForProduct(product.type, product.usage_key || undefined)
        const nextPeriodCustomLimit = getNextPeriodCustomLimitForProduct(product.type, product.usage_key || undefined)
        return {
            type: product.type,
            name: product.name,
            description: product.description || '',
            is_used: (product.current_usage || 0) > 0,
            has_exceeded_limit: product.percentage_usage > 1,
            current_usage: product.current_usage,
            usage_limit: product.tiered && product.tiers ? product.tiers?.[0].up_to : product.free_allocation,
            percentage_usage: product.percentage_usage || 0,
            custom_limit_usd: customLimit,
            next_period_custom_limit_usd: nextPeriodCustomLimit,
            docs_url: product.docs_url,
        }
    })

    const maxAddons: MaxAddonInfo[] = (billing.products || [])
        .flatMap((product) => (product.addons || []).map((addon) => ({ product, addon })))
        .filter(({ product, addon }) => isAddonVisible(product, addon, featureFlags))
        .map(({ addon }) => {
            const customLimit = getCustomLimitForProduct(addon.type, addon.usage_key || undefined)
            const nextPeriodCustomLimit = getNextPeriodCustomLimitForProduct(addon.type, addon.usage_key || undefined)

            return {
                type: addon.type,
                name: addon.name,
                description: addon.description || '',
                is_used: (addon.current_usage || 0) > 0,
                has_exceeded_limit: (addon.percentage_usage || 0) > 1,
                current_usage: addon.current_usage || 0,
                usage_limit: addon.usage_limit,
                percentage_usage: addon.percentage_usage,
                custom_limit_usd: customLimit,
                next_period_custom_limit_usd: nextPeriodCustomLimit,
                docs_url: addon.docs_url || undefined,
            }
        })

    return {
        has_active_subscription: billing.has_active_subscription || false,
        subscription_level: billing.has_active_subscription ? 'paid' : 'free',
        billing_plan: billing.billing_plan || null,
        is_deactivated: billing.deactivated,
        products: maxProducts,
        addons: maxAddons,
        total_current_amount_usd: billing.current_total_amount_usd,
        total_projected_amount_usd: billing.projected_total_amount_usd,
        startup_program_label: billing.startup_program_label || undefined,
        startup_program_label_previous: billing.startup_program_label_previous || undefined,
        trial: billing.trial
            ? {
                  is_active: billing.trial.status === 'active',
                  expires_at: billing.trial.expires_at,
                  target: billing.trial.target,
              }
            : undefined,
        billing_period: billing.billing_period
            ? {
                  current_period_start: billing.billing_period.current_period_start.format('YYYY-MM-DD'),
                  current_period_end: billing.billing_period.current_period_end.format('YYYY-MM-DD'),
                  interval: billing.billing_period.interval,
              }
            : undefined,
        usage_history: usageResponse?.results,
        settings: {
            autocapture_on: !currentTeam.autocapture_opt_out,
            active_destinations: destinations.length,
        },
    }
}
