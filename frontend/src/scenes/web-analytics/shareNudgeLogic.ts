import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import type { shareNudgeLogicType } from './shareNudgeLogicType'

const FLAG = FEATURE_FLAGS.WEB_ANALYTICS_SHARE_NUDGE_V2
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
    subscriptions(({ cache }) => ({
        variant: (variant: string | null) => {
            if (variant && !cache.exposed) {
                cache.exposed = true
                posthog.capture('web analytics share nudge exposed', { variant })
            }
        },
    })),
])
