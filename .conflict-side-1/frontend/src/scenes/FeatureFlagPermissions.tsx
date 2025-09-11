import { AccessControlPopoutCTA } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlPopoutCTA'
import { AccessControlResourceType, FeatureFlagType } from '~/types'

export function FeatureFlagPermissions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    if (!featureFlag.id) {
        return <p>Please save the feature flag before changing the access controls.</p>
    }
    return <AccessControlPopoutCTA resourceType={AccessControlResourceType.FeatureFlag} />
}
