import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { IngestionWizardV2 } from './v2/IngestionWizard'
import { IngestionWizardV1 } from './v1/IngestionWizard'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: IngestionWizard,
}

export function IngestionWizard(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.ONBOARDING_V2_EXPERIMENT] === 'test') {
        return <IngestionWizardV2 />
    }

    return <IngestionWizardV1 />
}
