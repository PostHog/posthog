import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import type { shareNudgeLogicType } from './shareNudgeLogicType'

const FLAG = FEATURE_FLAGS.WEB_ANALYTICS_SHARE_NUDGE
const DASHBOARD_SELECTOR = '[data-attr="web-analytics-dashboard"]'
const HOVER_DWELL_MS = 2500

export interface PromptAnchor {
    x: number
    y: number
}

export const shareNudgeLogic = kea<shareNudgeLogicType>([
    path(['scenes', 'web-analytics', 'shareNudgeLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        showPrompt: (anchor: PromptAnchor) => ({ anchor }),
        dismissForSession: true,
    }),
    reducers({
        promptVisible: [
            false,
            {
                showPrompt: () => true,
                dismissForSession: () => false,
            },
        ],
        promptAnchor: [
            null as PromptAnchor | null,
            {
                showPrompt: (_, { anchor }) => anchor,
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
        showBanner: [(s) => [s.variant], (variant): boolean => variant === 'banner'],
        emphasizeShareButton: [(s) => [s.variant], (variant): boolean => variant === 'button'],
        intentPromptEnabled: [(s) => [s.variant], (variant): boolean => variant === 'prompt'],
    }),
    listeners(() => ({
        showPrompt: () => {
            posthog.capture('web analytics share nudge prompt shown')
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
                    const rect = selection.getRangeAt(0).getBoundingClientRect()
                    actions.showPrompt({ x: rect.left, y: rect.bottom })
                }

                const onMouseOver = (event: MouseEvent): void => {
                    if (!shouldTrigger()) {
                        return
                    }
                    const target = event.target as HTMLElement | null
                    if (!target?.closest?.(DASHBOARD_SELECTOR)) {
                        return
                    }
                    const x = event.clientX
                    const y = event.clientY
                    cache.disposables.add(() => {
                        const timer = setTimeout(() => {
                            if (shouldTrigger()) {
                                actions.showPrompt({ x, y })
                            }
                        }, HOVER_DWELL_MS)
                        return () => clearTimeout(timer)
                    }, 'shareNudgeHoverDwell')
                }

                document.addEventListener('mouseup', onMouseUp)
                document.addEventListener('mouseover', onMouseOver)
                return () => {
                    document.removeEventListener('mouseup', onMouseUp)
                    document.removeEventListener('mouseover', onMouseOver)
                    cache.disposables.dispose('shareNudgeHoverDwell')
                }
            }, 'shareNudgeIntentListeners')
        },
    })),
])
