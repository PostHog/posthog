import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'

import { OfflineEvaluationsTab, offlineEvaluationsLogic } from './offlineEvaluationsLogic'

export function OfflineEvaluationsTabs({ activeTab }: { activeTab: OfflineEvaluationsTab }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { setActiveTab } = useActions(offlineEvaluationsLogic)
    const offlineEvaluationsEnabled = !!featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS]

    return (
        <LemonSegmentedButton
            size="small"
            value={activeTab}
            onChange={setActiveTab}
            options={[
                {
                    value: 'experiments',
                    label: (
                        <span className="flex items-center gap-1">
                            <span>Experiments</span>
                            {!offlineEvaluationsEnabled && (
                                <LemonTag type="muted" size="small">
                                    Coming soon
                                </LemonTag>
                            )}
                        </span>
                    ),
                    disabledReason: !offlineEvaluationsEnabled
                        ? 'Offline experiments are coming soon.'
                        : getProductAccessDisabledReason({
                              sceneKey: Scene.AIObservabilityOfflineExperiment,
                              displayLabel: 'experiments',
                          }),
                },
                {
                    value: 'datasets',
                    label: 'Datasets',
                    disabledReason: getProductAccessDisabledReason({
                        sceneKey: Scene.AIObservabilityDatasets,
                        displayLabel: 'datasets',
                    }),
                },
            ]}
        />
    )
}
