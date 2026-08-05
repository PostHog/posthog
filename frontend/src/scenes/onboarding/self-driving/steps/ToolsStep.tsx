import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { SelfDrivingGoal } from '../goals'
import { goalSelectionLogic } from '../goalSelectionLogic'
import { type EnablementProduct, productEnablementStepLogic } from '../productEnablementStepLogic'

interface ToolRow {
    iconType: 'product_analytics' | 'session_replay' | 'error_tracking' | 'web_analytics' | 'llm_analytics'
    name: string
    benefit: string
    /** The team toggle backing this row, when there is one. Tools without a toggle are on as soon
     * as data flows, so their row is pure showcase. */
    product?: EnablementProduct
}

const ANALYTICS_ROW: ToolRow = {
    iconType: 'product_analytics',
    name: 'Product analytics',
    benefit: 'Events, trends, and funnels start flowing as soon as the SDK is in.',
}
const REPLAY_ROW: ToolRow = {
    iconType: 'session_replay',
    name: 'Session replay',
    benefit: 'Real sessions recorded, so agents can watch what users did.',
    product: 'session_replay',
}
const ERROR_TRACKING_ROW: ToolRow = {
    iconType: 'error_tracking',
    name: 'Error tracking',
    benefit: 'Exceptions grouped into issues that feed your agents.',
    product: 'error_tracking',
}
const WEB_ANALYTICS_ROW: ToolRow = {
    iconType: 'web_analytics',
    name: 'Web analytics',
    benefit: 'Traffic, sources, and conversion on a live dashboard.',
}
const AI_OBSERVABILITY_ROW: ToolRow = {
    iconType: 'llm_analytics',
    name: 'AI observability',
    benefit: 'Traces, costs, and failures from your LLM features.',
}

/** Each goal's tool collection - what the flow configures for it, toggleable or not. */
function rowsForGoal(goal: SelfDrivingGoal | null): ToolRow[] {
    switch (goal) {
        case 'user_behavior':
            return [ANALYTICS_ROW, REPLAY_ROW]
        case 'fix_issues':
            return [ERROR_TRACKING_ROW, REPLAY_ROW]
        case 'website_traffic':
            return [WEB_ANALYTICS_ROW, ANALYTICS_ROW]
        case 'ai_app':
            return [AI_OBSERVABILITY_ROW, ANALYTICS_ROW]
        default:
            return [ANALYTICS_ROW, REPLAY_ROW, ERROR_TRACKING_ROW]
    }
}

/**
 * Shows the goal's tool collection, already turned on by goal selection - transparency, not a
 * decision. The inline "Turn on" button appears only when an auto-enable call failed (e.g. the
 * toggle is admin-gated), so that failure path keeps a home without a screen per product.
 */
export function ToolsStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { selectedGoal } = useValues(goalSelectionLogic)
    const { isSessionReplayEnabled, isErrorTrackingEnabled, enablingProduct, autoEnabling } =
        useValues(productEnablementStepLogic)
    const { enableProduct, registerAnalyticsIntent } = useActions(productEnablementStepLogic)

    const rows = rowsForGoal(selectedGoal)
    const showsAnalytics = rows.includes(ANALYTICS_ROW)

    useOnMountEffect(() => {
        if (showsAnalytics) {
            registerAnalyticsIntent()
        }
    })

    return (
        <div className="flex flex-col gap-6 py-1">
            <p className="text-secondary text-center m-0">
                These are on and feeding your agents. You can change them later in settings.
            </p>
            <div className="flex flex-col gap-3">
                {rows.map((row) => {
                    const colorVar = `var(--color-product-${row.iconType.replace(/_/g, '-')}-light)`
                    const isOn = !row.product
                        ? true
                        : row.product === 'session_replay'
                          ? isSessionReplayEnabled
                          : isErrorTrackingEnabled
                    return (
                        <div
                            key={row.name}
                            className="OnboardingProductCard flex items-center gap-4 p-4 rounded-lg border"
                        >
                            <div
                                className="size-12 shrink-0 rounded-lg flex items-center justify-center"
                                style={{ background: `color-mix(in srgb, ${colorVar} 12%, transparent)` }}
                            >
                                <div className="flex *:text-2xl group/colorful-product-icons colorful-product-icons-true">
                                    {iconForType(row.iconType)}
                                </div>
                            </div>
                            <div className="flex-1 flex flex-col gap-0.5 min-w-0">
                                <div className="font-semibold text-base">{row.name}</div>
                                <div className="text-sm text-secondary text-balance">{row.benefit}</div>
                            </div>
                            {isOn ? (
                                <div className="flex items-center gap-1.5 text-sm text-success shrink-0">
                                    <span className="size-2 rounded-full bg-success" />
                                    Enabled
                                </div>
                            ) : (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    loading={autoEnabling || enablingProduct === row.product}
                                    onClick={() => row.product && enableProduct(row.product)}
                                >
                                    Turn on
                                </LemonButton>
                            )}
                        </div>
                    )
                })}
            </div>
            <div className="flex justify-center">
                <LemonButton type="primary" status="alt" onClick={onContinue}>
                    Continue
                </LemonButton>
            </div>
        </div>
    )
}
