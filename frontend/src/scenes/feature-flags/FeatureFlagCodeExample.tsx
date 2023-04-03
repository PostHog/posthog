import { FeatureFlagType } from '~/types'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'

export function FeatureFlagCodeExample({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return (
        <div>
            <h3>
                <b>How to implement</b>
            </h3>
            <FeatureFlagInstructions
                newCodeExample={true}
                featureFlag={featureFlag}
                featureFlagKey={featureFlag.key || 'my-flag'}
            />
        </div>
    )
}
