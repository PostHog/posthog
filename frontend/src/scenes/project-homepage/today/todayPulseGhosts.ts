import type { CustomerAnalyticsConfig } from '~/queries/schema/schema-general'

export interface TodayPulseGhost {
    key: 'activity_event' | 'signup_event' | 'payment_event' | 'subscription_event'
    name: string
    configured: boolean
}

const KEY_METRICS: Pick<TodayPulseGhost, 'key' | 'name'>[] = [
    { key: 'activity_event', name: 'Active users' },
    { key: 'signup_event', name: 'Sign-ups' },
    { key: 'payment_event', name: 'Payments' },
    { key: 'subscription_event', name: 'Subscriptions' },
]

function isConfigured(node: unknown): boolean {
    const kind = (node as { kind?: string } | null | undefined)?.kind
    return kind === 'EventsNode' || kind === 'ActionsNode'
}

export function pulseGhosts(config: CustomerAnalyticsConfig | null | undefined): TodayPulseGhost[] {
    return KEY_METRICS.map((metric) => ({ ...metric, configured: isConfigured(config?.[metric.key]) }))
}
