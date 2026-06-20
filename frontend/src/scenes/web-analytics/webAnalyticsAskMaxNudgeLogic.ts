import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { webAnalyticsAskMaxNudgeLogicType } from './webAnalyticsAskMaxNudgeLogicType'

const FLAG = FEATURE_FLAGS.WEB_ANALYTICS_ASK_MAX_NUDGE

const UNION_DWELL_MS = 45_000
const SHOW_DELAY_MS: Record<string, number> = {
    aggressive: 45_000,
    balanced: 60_000,
    conservative: 90_000,
}
const COOLDOWN_MS = 30 * 24 * 60 * 60 * 1000
const DEAD_CLICK_THRESHOLD = 2

const DWELL_TIMER = 'askMaxNudgeDwell'
const SHOW_TIMER = 'askMaxNudgeShow'
const disposeNudgeTimers = (disposables: { dispose: (key: string) => boolean }): void => {
    disposables.dispose(DWELL_TIMER)
    disposables.dispose(SHOW_TIMER)
}

const ENGAGEMENT_EVENTS = new Set([
    'web analytics filter applied',
    'web analytics date range changed',
    'web analytics compare toggled',
])

export type NudgeTriggerReason = 'dwell' | 'frustration'

export const webAnalyticsAskMaxNudgeLogic = kea<webAnalyticsAskMaxNudgeLogicType>([
    path(['scenes', 'web-analytics', 'webAnalyticsAskMaxNudgeLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        markEngaged: true,
        registerFrustration: true,
        enroll: (reason: NudgeTriggerReason) => ({ reason }),
        showNudge: (reason: NudgeTriggerReason) => ({ reason }),
        dismissNudge: true,
        nudgeClicked: true,
        markEligibleReported: true,
        markShownAt: (at: number) => ({ at }),
        markDismissedAt: (at: number) => ({ at }),
    }),
    reducers({
        eligibleReported: [false, { persist: true }, { markEligibleReported: () => true }],
        lastShownAt: [null as number | null, { persist: true }, { markShownAt: (_, { at }) => at }],
        lastDismissedAt: [null as number | null, { persist: true }, { markDismissedAt: (_, { at }) => at }],
        engaged: [false, { markEngaged: () => true }],
        promptVisible: [
            false,
            {
                showNudge: () => true,
                dismissNudge: () => false,
                nudgeClicked: () => false,
            },
        ],
        triggerReason: [
            null as NudgeTriggerReason | null,
            {
                enroll: (_, { reason }) => reason,
                showNudge: (_, { reason }) => reason,
            },
        ],
    }),
    selectors({
        variant: [
            (s) => [s.featureFlags],
            (featureFlags): string | null => {
                const value = featureFlags[FLAG]
                return typeof value === 'string' ? value : null
            },
        ],
        isTreatment: [(s) => [s.variant], (variant): boolean => variant !== null && variant !== 'control'],
        cooldownElapsed: [
            (s) => [s.lastShownAt, s.lastDismissedAt],
            (lastShownAt, lastDismissedAt): boolean => {
                const last = Math.max(lastShownAt ?? 0, lastDismissedAt ?? 0)
                return last === 0 || Date.now() - last >= COOLDOWN_MS
            },
        ],
        canTrigger: [
            (s) => [s.engaged, s.cooldownElapsed, s.promptVisible],
            (engaged, cooldownElapsed, promptVisible): boolean => !engaged && cooldownElapsed && !promptVisible,
        ],
    }),
    listeners(({ values, actions, cache }) => ({
        markEngaged: () => {
            disposeNudgeTimers(cache.disposables)
        },
        registerFrustration: () => {
            if (!values.variant || !values.canTrigger) {
                return
            }
            actions.enroll('frustration')
            if (values.isTreatment) {
                actions.showNudge('frustration')
            }
            disposeNudgeTimers(cache.disposables)
        },
        enroll: ({ reason }) => {
            if (values.eligibleReported || !values.variant) {
                return
            }
            actions.markEligibleReported()
            posthog.capture('web analytics max nudge eligible', { variant: values.variant, trigger_reason: reason })
        },
        showNudge: ({ reason }) => {
            actions.markShownAt(Date.now())
            posthog.capture('web analytics max nudge shown', { variant: values.variant, trigger_reason: reason })
        },
        dismissNudge: () => {
            actions.markDismissedAt(Date.now())
            posthog.capture('web analytics max nudge dismissed', {
                variant: values.variant,
                trigger_reason: values.triggerReason,
            })
        },
        nudgeClicked: () => {
            actions.markShownAt(Date.now())
            posthog.capture('web analytics max nudge clicked', {
                variant: values.variant,
                trigger_reason: values.triggerReason,
            })
        },
    })),
    subscriptions(({ values, actions, cache }) => ({
        variant: (variant: string | null) => {
            disposeNudgeTimers(cache.disposables)
            if (!variant) {
                return
            }

            cache.disposables.add(() => {
                const timer = setTimeout(() => {
                    if (values.canTrigger) {
                        actions.enroll('dwell')
                    }
                }, UNION_DWELL_MS)
                return () => clearTimeout(timer)
            }, DWELL_TIMER)

            if (variant !== 'control') {
                const delayMs = SHOW_DELAY_MS[variant] ?? UNION_DWELL_MS
                cache.disposables.add(() => {
                    const timer = setTimeout(() => {
                        if (values.canTrigger) {
                            actions.enroll('dwell')
                            actions.showNudge('dwell')
                        }
                    }, delayMs)
                    return () => clearTimeout(timer)
                }, SHOW_TIMER)
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        cache.deadClicks = 0
        cache.disposables.add(() => {
            return posthog.on('eventCaptured', (capturedEvent) => {
                const name = capturedEvent?.event
                if (!name) {
                    return
                }
                if (ENGAGEMENT_EVENTS.has(name)) {
                    actions.markEngaged()
                } else if (name === '$rageclick') {
                    actions.registerFrustration()
                } else if (name === '$dead_click') {
                    cache.deadClicks = (cache.deadClicks ?? 0) + 1
                    if (cache.deadClicks >= DEAD_CLICK_THRESHOLD) {
                        actions.registerFrustration()
                    }
                }
            })
        }, 'askMaxNudgeCaptureHook')
    }),
])
