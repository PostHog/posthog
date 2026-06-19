import { type ProductKey } from '~/queries/schema/schema-general'

import { type OnboardingStepKey } from '../onboardingLogic'
import { type MetricCard, type PreviewConfig } from './types'

/** Live onboarding state the presets read from. */
export interface PreviewContext {
    orgName: string
    products: ProductKey[]
    logoUrl?: string | null
}

const DASHBOARD_METRICS: MetricCard[] = [
    { label: 'Unique visitors', value: '48,291', delta: '12.4%', deltaPositive: true },
    { label: 'Pageviews', value: '193k', delta: '8.1%', deltaPositive: true },
    { label: 'Conversion', value: '3.2%', delta: '0.4%', deltaPositive: true },
]

const orgIdentity = (ctx: PreviewContext): PreviewConfig['org'] => ({
    name: ctx.orgName.trim() || 'Your organization',
    logoUrl: ctx.logoUrl ?? null,
})

/** A populated dashboard reflecting the user's chosen products, or an empty state if none are chosen yet. */
const workspaceConfig = (ctx: PreviewContext): PreviewConfig => ({
    org: orgIdentity(ctx),
    sidebar: { products: ctx.products, activeProductKey: ctx.products[0] ?? null },
    page: ctx.products.length
        ? { kind: 'dashboard', metrics: DASHBOARD_METRICS, showTrend: true, showBars: true }
        : { kind: 'empty', title: 'Pick what you’re building', subtitle: 'We’ll set up the right products for you.' },
})

/** Per-step preview configuration. Each step derives a full PreviewConfig from live onboarding state. */
export const PREVIEW_PRESETS: Record<OnboardingStepKey, (ctx: PreviewContext) => PreviewConfig> = {
    create_org: (ctx) => ({
        org: orgIdentity(ctx),
        sidebar: { products: ctx.products },
        page: { kind: 'empty', title: 'Your workspace is taking shape', subtitle: 'Name your organization to begin.' },
    }),
    company: workspaceConfig,
    install: workspaceConfig,
    configure: workspaceConfig,
    learn: workspaceConfig,
    done: workspaceConfig,
}

export function buildPreviewConfig(stepKey: OnboardingStepKey, ctx: PreviewContext): PreviewConfig {
    return (PREVIEW_PRESETS[stepKey] ?? PREVIEW_PRESETS.create_org)(ctx)
}
