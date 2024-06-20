import { LemonBanner, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { upgradeModalLogic } from './upgradeModalLogic'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureKey, upgradeModalFeatureUsage, upgradeModalIsGrandfathered } =
        useValues(upgradeModalLogic)
    const { hideUpgradeModal } = useActions(upgradeModalLogic)

    return upgradeModalFeatureKey ? (
        <LemonModal onClose={hideUpgradeModal} isOpen={!!upgradeModalFeatureKey}>
            <div className="max-w-2xl">
                <PayGateMini
                    feature={upgradeModalFeatureKey}
                    currentUsage={upgradeModalFeatureUsage ?? undefined}
                    isGrandfathered={upgradeModalIsGrandfathered ?? undefined}
                    background={false}
                >
                    <LemonBanner type="error">
                        There's been an error retrieving your billing info. Please try again in a few minutes. If you
                        are still seeing this modal, please let us know.
                    </LemonBanner>
                </PayGateMini>
            </div>
        </LemonModal>
    ) : (
        <></>
    )
}
