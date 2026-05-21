import { FeaturePreviewSceneGate } from '~/layout/scenes/components/FeaturePreviewSceneGate'

import { customerAnalyticsAccountsFeaturePreviewGate } from '../../featurePreviewGate'
import { AccountsTabContent } from './AccountsTabContent'

export function AccountsTab(): JSX.Element {
    return (
        <FeaturePreviewSceneGate config={customerAnalyticsAccountsFeaturePreviewGate}>
            <AccountsTabContent />
        </FeaturePreviewSceneGate>
    )
}
