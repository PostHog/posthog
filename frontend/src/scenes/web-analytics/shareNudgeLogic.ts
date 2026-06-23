import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import type { shareNudgeLogicType } from './shareNudgeLogicType'

const FLAG = FEATURE_FLAGS.WEB_ANALYTICS_SHARE_NUDGE_V2
const DASHBOARD_SELECTOR = '[data-attr="web-analytics-dashboard"]'
const HOVER_DWELL_MS = 2500
const EXPORT_PROMPT_PROBABILITY = 0.25

export const shareNudgeLogic = kea<shareNudgeLogicType>([
    path(['scenes', 'web-analytics', 'shareNudgeLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        showPrompt: (source: string) => ({ source }),
        dismissForSession: true,
        exportTriggered: true,
    }),
    reducers({
        promptVisible: [
            false,
            {
                showPrompt: () => true,
                dismissForSession: () => false,
            },
        ],
        promptSource: [
            null as string | null,
            {
                showPrompt: (_, { source }) => source,
            },
        ],
        sessionDismissed: [
            false,
            {
                dismissForSession: () => true,
            },
        ],
    }),
    selectors({
        hasColleagues: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => (currentOrganization?.member_count ?? 1) >= 2,
        ],
        variant: [
            (s) => [s.featureFlags, s.hasColleagues],
            (featureFlags, hasColleagues): string | null => {
                const flag = featureFlags[FLAG]
                return hasColleagues && typeof flag === 'string' ? flag : null
            },
        ],
        showBanner: [
            (s) => [s.variant, s.sessionDismissed],
            (variant, sessionDismissed): boolean => variant === 'banner' && !sessionDismissed,
        ],
        emphasizeShareButton: [(s) => [s.variant], (variant): boolean => variant === 'button'],
        intentPromptEnabled: [(s) => [s.variant], (variant): boolean => variant === 'prompt'],
        exportPromptEnabled: [(s) => [s.variant], (variant): boolean => variant === 'export'],
    }),
    listeners(({ values, actions }) => ({
        showPrompt: ({ source }) => {
            posthog.capture('web analytics share nudge prompt shown', { source })
        },
        exportTriggered: () => {
            if (!values.exportPromptEnabled || values.sessionDismissed) {
                return
            }
            if (Math.random() >= EXPORT_PROMPT_PROBABILITY) {
                return
            }
            actions.showPrompt('export_prompt')
        },
    })),
    subscriptions(({ values, actions, cache }) => ({
        variant: (variant: string | null) => {
            if (variant && !cache.exposed) {
                cache.exposed = true
                posthog.capture('web analytics share nudge exposed', { variant })
            }

            if (variant !== 'prompt') {
                cache.disposables.dispose('shareNudgeIntentListeners')
                return
            }

            cache.disposables.add(() => {
                const shouldTrigger = (): boolean =>
                    values.intentPromptEnabled && !values.sessionDismissed && !values.promptVisible

                const onMouseUp = (): void => {
                    if (!shouldTrigger()) {
                        return
                    }
                    const selection = window.getSelection()
                    const text = selection?.toString().trim()
                    if (!text || text.length < 2 || !selection?.anchorNode) {
                        return
                    }
                    const container = document.querySelector(DASHBOARD_SELECTOR)
                    if (!container || !container.contains(selection.anchorNode)) {
                        return
                    }
                    actions.showPrompt('intent_prompt')
                }

                const onMouseMove = (event: MouseEvent): void => {
                    const target = event.target as HTMLElement | null
                    if (!shouldTrigger() || !target?.closest?.(DASHBOARD_SELECTOR)) {
                        cache.disposables.dispose('shareNudgeHoverDwell')
                        return
                    }
                    cache.disposables.add(() => {
                        const timer = setTimeout(() => {
                            if (shouldTrigger()) {
                                actions.showPrompt('intent_prompt')
                            }
                        }, HOVER_DWELL_MS)
                        return () => clearTimeout(timer)
                    }, 'shareNudgeHoverDwell')
                }

                document.addEventListener('mouseup', onMouseUp)
                document.addEventListener('mousemove', onMouseMove)
                return () => {
                    document.removeEventListener('mouseup', onMouseUp)
                    document.removeEventListener('mousemove', onMouseMove)
                    cache.disposables.dispose('shareNudgeHoverDwell')
                }
            }, 'shareNudgeIntentListeners')
        },
    })),
])
