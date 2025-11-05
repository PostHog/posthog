import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { FeatureFlagType } from '~/types'

import { FeatureFlagInstructions } from './FeatureFlagInstructions'

export function FeatureFlagCodeExample({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <SceneSection title="How to implement" description="Use the following code to implement this feature flag.">
            <FeatureFlagInstructions featureFlag={featureFlag} />
        </SceneSection>
    )
}
