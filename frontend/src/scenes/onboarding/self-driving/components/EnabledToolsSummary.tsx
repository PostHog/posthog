import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { SelfDrivingGoal } from '../goals'
import { goalSelectionLogic } from '../goalSelectionLogic'
import { type EnablementProduct, productEnablementStepLogic } from '../productEnablementStepLogic'

interface ToolRow {
    iconType: 'product_analytics' | 'session_replay' | 'error_tracking'
    name: string
    benefit: string
    /** Which team toggle backs this row; analytics has none - it's on as soon as the SDK is in. */
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

/** Mirrors what goal selection auto-enabled, plus analytics where it's part of the goal's loop. */
function rowsForGoal(goal: SelfDrivingGoal | null): ToolRow[] {
    switch (goal) {
        case 'user_behavior':
            return [ANALYTICS_ROW, REPLAY_ROW]
        case 'fix_issues':
            return [ERROR_TRACKING_ROW, REPLAY_ROW]
        case 'website_traffic':
        case 'ai_app':
            return []
        default:
            return [ANALYTICS_ROW, REPLAY_ROW, ERROR_TRACKING_ROW]
    }
}

/**
 * The install step's "what we turned on for you" list: goal selection already enabled these, so
 * this is transparency rather than a decision. The inline "Turn on" button only appears when an
 * auto-enable call failed (e.g. admin-gated), giving that failure path a home without a screen.
 */
export function EnabledToolsSummary(): JSX.Element | null {
    const { selectedGoal } = useValues(goalSelectionLogic)
    const { isSessionReplayEnabled, isErrorTrackingEnabled, enablingProduct } = useValues(productEnablementStepLogic)
    const { enableProduct, registerAnalyticsIntent } = useActions(productEnablementStepLogic)

    const rows = rowsForGoal(selectedGoal)
    const showsAnalytics = rows.includes(ANALYTICS_ROW)

    useOnMountEffect(() => {
        if (showsAnalytics) {
            registerAnalyticsIntent()
        }
    })

    if (rows.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-muted uppercase tracking-wide">Already on for you</span>
            <div className="flex flex-col">
                {rows.map((row) => {
                    const isOn = !row.product
                        ? true
                        : row.product === 'session_replay'
                          ? isSessionReplayEnabled
                          : isErrorTrackingEnabled
                    return (
                        <div key={row.name} className="flex items-center gap-3 py-2 border-b last:border-b-0">
                            <div className="flex *:text-xl group/colorful-product-icons colorful-product-icons-true shrink-0">
                                {iconForType(row.iconType)}
                            </div>
                            <div className="flex-1 min-w-0">
                                <span className="text-sm font-semibold">{row.name}</span>
                                <span className="text-xs text-secondary block">{row.benefit}</span>
                            </div>
                            {isOn ? (
                                <div className="flex items-center gap-1.5 text-xs text-success shrink-0">
                                    <span className="size-1.5 rounded-full bg-success" />
                                    Enabled
                                </div>
                            ) : (
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    loading={enablingProduct === row.product}
                                    onClick={() => row.product && enableProduct(row.product)}
                                >
                                    Turn on
                                </LemonButton>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
