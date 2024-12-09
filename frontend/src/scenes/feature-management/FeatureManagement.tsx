import { SceneExport } from 'scenes/sceneTypes'

import { FeatureManagementDetail } from './FeatureManagementDetail'
import { FeatureManagementList } from './FeatureManagementList'
import { featureManagementLogic } from './featureManagementLogic'

export const scene: SceneExport = {
    component: FeatureManagement,
    logic: featureManagementLogic,
}

export function FeatureManagement(): JSX.Element {
    return (
        <div className="flex gap-4">
            <div className="w-1/6 space-y-px">
                <FeatureManagementList />
            </div>

            <div className="w-5/6">
                <FeatureManagementDetail />
            </div>
        </div>
    )
}
