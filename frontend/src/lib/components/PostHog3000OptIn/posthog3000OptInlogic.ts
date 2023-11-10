import { actions, kea, reducers, path, listeners, connect } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog from 'posthog-js'

export enum SidePanelTab {
    Notebooks = 'notebook',
    Feedback = 'feedback',
    Docs = 'docs',
    Activation = 'activation',
    Settings = 'settings',
}

export const posthog3000OptInlogic = kea([
    path(['lib', 'posthog3000OptIn', 'posthog3000OptInlogic']),
    actions({
        dismissNotice: true,
        optIn: true,
    }),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    reducers(() => ({
        noticeDismissed: [
            false,
            { persist: true },
            {
                dismissNotice: (_, { tab }) => tab,
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        optIn: () => {
            posthog.updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.POSTHOG_3000, true)
        },
        optOut: () => {
            posthog.updateEarlyAccessFeatureEnrollment(FEATURE_FLAGS.POSTHOG_3000, false)
        },
        // openSidePanel: () => {
        //     actions.setSidePanelOpen(true)
        // },
        // closeSidePanel: ({ tab }) => {
        //     if (!tab) {
        //         // If we aren't specifiying the tab we always close
        //         actions.setSidePanelOpen(false)
        //     } else if (values.selectedTab === tab) {
        //         // Otherwise we only close it if the tab is the currently open one
        //         actions.setSidePanelOpen(false)
        //     }
        // },
    })),
])
