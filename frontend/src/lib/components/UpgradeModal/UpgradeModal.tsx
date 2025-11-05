import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

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
                    handleSubmit={hideUpgradeModal}
                >
                    <div className="pr-7">
                        You should have access to this feature already. If you are still seeing this modal, please let
                        us know 🙂
                    </div>
                </PayGateMini>
            </div>
        </LemonModal>
    ) : (
        <></>
    )
}
