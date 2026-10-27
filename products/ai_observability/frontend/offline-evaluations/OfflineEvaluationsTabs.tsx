import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'

import { OfflineEvaluationsTab, offlineEvaluationsLogic } from './offlineEvaluationsLogic'

export function OfflineEvaluationsTabs({ activeTab }: { activeTab: OfflineEvaluationsTab }): JSX.Element {
    const { datasetsEnabled, offlineEvaluationsEnabled } = useValues(offlineEvaluationsLogic)
    const { setActiveTab } = useActions(offlineEvaluationsLogic)

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
                    disabledReason: !datasetsEnabled
                        ? 'Datasets are coming soon.'
                        : getProductAccessDisabledReason({
                              sceneKey: Scene.AIObservabilityDatasets,
                              displayLabel: 'datasets',
                          }),
                },
            ]}
        />
    )
}
