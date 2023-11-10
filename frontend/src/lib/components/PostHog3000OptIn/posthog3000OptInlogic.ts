import { actions, kea, reducers, path, listeners, connect } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog from 'posthog-js'

import type { posthog3000OptInlogicType } from './posthog3000OptInlogicType'

export enum SidePanelTab {
    Notebooks = 'notebook',
    Feedback = 'feedback',
    Docs = 'docs',
    Activation = 'activation',
    Settings = 'settings',
}

export const posthog3000OptInlogic = kea<posthog3000OptInlogicType>([
    path(['lib', 'posthog3000OptIn', 'posthog3000OptInlogic']),
    actions({
        dismissNotice: true,
        optIn: true,
        optOut: true,
    }),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    reducers(() => ({
        noticeDismissed: [
            false,
            { persist: true },
            {
                dismissNotice: () => true,
                optIn: () => false,
                optOut: () => false,
            },
        ],
    })),

    listeners(() => ({
        optIn: () => {
            posthog.updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.POSTHOG_3000, true)
        },
        optOut: () => {
            posthog.updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.POSTHOG_3000, false)

            // TODO: Swap this out for `posthog.startSurvey()` once it's available
            document.body.classList.add('posthog-3000-opt-out')
        },
    })),
])
