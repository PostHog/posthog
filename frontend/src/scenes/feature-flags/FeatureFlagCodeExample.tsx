import { FeatureFlagType } from '~/types'

import { FeatureFlagInstructions } from './FeatureFlagInstructions'

export function FeatureFlagCodeExample({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <div>
            <h3 className="l3">How to implement</h3>
            <FeatureFlagInstructions featureFlag={featureFlag} />
        </div>
    )
}
