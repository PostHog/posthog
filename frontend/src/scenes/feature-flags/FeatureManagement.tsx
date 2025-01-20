import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { FeatureManagementDetail } from './FeatureManagementDetail'
import { featureManagementLogic } from './featureManagementLogic'

export const scene: SceneExport = {
    component: FeatureManagement,
    logic: featureManagementLogic,
}

export function FeatureManagement(): JSX.Element {
    const { activeFeatureId, features } = useValues(featureManagementLogic)
    const { setActiveFeatureId } = useActions(featureManagementLogic)

    return (
        <div className="flex gap-4">
            <ul className="w-1/6 space-y-px">
                {features.results.map((feature) => (
                    <li key={feature.id}>
                        <LemonButton
                            onClick={() => setActiveFeatureId(feature.id)}
                            size="small"
                            fullWidth
                            active={activeFeatureId === feature.id}
                        >
                            <span className="truncate">{feature.name}</span>
                        </LemonButton>
                    </li>
                ))}
            </ul>
            <div className="w-5/6">
                <FeatureManagementDetail />
            </div>
        </div>
    )
}
