import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'

import { OfflineEvaluationsTab, offlineEvaluationsLogic } from './offlineEvaluationsLogic'

export function OfflineEvaluationsTabs({ activeTab }: { activeTab: OfflineEvaluationsTab }): JSX.Element {
    const { datasetsEnabled } = useValues(offlineEvaluationsLogic)
    const { setActiveTab } = useActions(offlineEvaluationsLogic)

    return (
        <LemonSegmentedButton
            size="small"
            value={activeTab}
            onChange={setActiveTab}
            options={[
                {
                    value: 'experiments',
                    'data-attr': 'offline-evaluations-experiments-tab',
                    label: 'Experiments',
                    disabledReason: getProductAccessDisabledReason({
                        sceneKey: Scene.AIObservabilityOfflineExperiment,
                        displayLabel: 'experiments',
                    }),
                },
                {
                    value: 'datasets',
                    'data-attr': 'offline-evaluations-datasets-tab',
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
