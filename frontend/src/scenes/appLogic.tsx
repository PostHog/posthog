import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import type { appLogicType } from './appLogicType'

export const appLogic = kea<appLogicType>([
    path(['scenes', 'App']),
    connect([teamLogic, organizationLogic, preflightLogic]),
    actions({
        enableDelayedSpinner: true,
        ignoreFeatureFlags: true,
        showDevTools: true,
    }),
    reducers({
        showingDelayedSpinner: [false, { enableDelayedSpinner: () => true }],
        featureFlagsTimedOut: [false, { ignoreFeatureFlags: () => true }],
        showingDevTools: [false, { showDevTools: () => true }],
    }),
    selectors({
        showApp: [
            (s) => [
                userLogic.selectors.userLoading,
                userLogic.selectors.user,
                featureFlagLogic.selectors.receivedFeatureFlags,
                s.featureFlagsTimedOut,
                preflightLogic.selectors.preflightLoading,
                preflightLogic.selectors.preflight,
            ],
            (userLoading, user, receivedFeatureFlags, featureFlagsTimedOut, preflightLoading, preflight) => {
                return (
                    (!userLoading || user) &&
                    (receivedFeatureFlags || featureFlagsTimedOut) &&
                    (!preflightLoading || preflight)
                )
            },
        ],
    }),
    events(({ actions, cache }) => ({
        afterMount: () => {
            cache.spinnerTimeout = window.setTimeout(() => actions.enableDelayedSpinner(), 1000)
            cache.featureFlagTimeout = window.setTimeout(() => actions.ignoreFeatureFlags(), 3000)
        },
        beforeUnmount: () => {
            window.clearTimeout(cache.spinnerTimeout)
            window.clearTimeout(cache.featureFlagTimeout)
        },
    })),
    urlToAction(({ actions }) => ({
        '*': (_, __, hash) => {
            if ('kea' in hash) {
                actions.showDevTools()
            }
        },
    })),
])
