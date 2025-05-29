import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'

import { BillingType } from '~/types'

import { isLegacySharedMetric, shouldUseNewQueryRunnerForNewObjects } from '../utils'
import type { SharedMetric } from './sharedMetricLogic'
import type { sharedMetricsLogicType } from './sharedMetricsLogicType'

export enum SharedMetricsTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
}

export const sharedMetricsLogic = kea<sharedMetricsLogicType>([
    path(['scenes', 'experiments', 'sharedMetricsLogic']),
    connect(() => ({
        values: [featureFlagsLogic, ['featureFlags'], billingLogic, ['billing']],
    })),
    actions({
        setSharedMetricsTab: (tabKey: SharedMetricsTabs) => ({ tabKey }),
    }),

    loaders({
        sharedMetrics: [
            [] as SharedMetric[],
            {
                loadSharedMetrics: async () => {
                    const response = await api.get('api/projects/@current/experiment_saved_metrics')
                    return response.results as SharedMetric[]
                },
            },
        ],
    }),

    reducers({
        tab: [
            SharedMetricsTabs.All as SharedMetricsTabs,
            {
                setSharedMetricsTab: (_, { tabKey }) => tabKey,
            },
        ],
    }),
    listeners(() => ({
        setSharedMetricsTab: () => {
            router.actions.push('/experiments/shared-metrics')
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSharedMetrics()
        },
    })),
    selectors(() => ({
        showLegacyBadge: [
            (s) => [featureFlagsLogic.selectors.featureFlags, s.sharedMetrics, billingLogic.selectors.billing],
            (featureFlags: FeatureFlagsSet, sharedMetrics: SharedMetric[], billing: BillingType): boolean => {
                /**
                 * If the new query runner is enabled, we want to always show the legacy badge,
                 * even if all existing shared metrics are using the legacy metric format.
                 *
                 * Not ideal to use feature flags at this level, but this is how things are and
                 * it'll take a while to change.
                 */
                if (shouldUseNewQueryRunnerForNewObjects(featureFlags, billing)) {
                    return true
                }

                /**
                 * If the new query runner is not enabled, we'll set this boolean selector
                 * so the components can show the legacy badge only if there are experiments
                 * that use the NEW query runner.
                 * This covers the case when the feature was disabled after creating new experiments.
                 */
                return sharedMetrics.some((sharedMetric) => !isLegacySharedMetric(sharedMetric))
            },
        ],
    })),
])
