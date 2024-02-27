import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { sceneLogic } from './sceneLogic'

export function UpgradeModal(): JSX.Element {
    const { upgradeModalFeatureKey, upgradeModalFeatureUsage, upgradeModalIsGrandfathered } = useValues(sceneLogic)
    const { hideUpgradeModal } = useActions(sceneLogic)

    return upgradeModalFeatureKey ? (
        <LemonModal onClose={hideUpgradeModal} isOpen={!!upgradeModalFeatureKey}>
            <div className="max-w-2xl">
                <PayGateMini
                    feature={upgradeModalFeatureKey}
                    currentUsage={upgradeModalFeatureUsage ?? undefined}
                    isGrandfathered={upgradeModalIsGrandfathered ?? undefined}
                    background={false}
                >
                    <>
                        You should have access to this feature already. If you are still seeing this modal, please let
                        us know 🙂
                    </>
                </PayGateMini>
            </div>
        </LemonModal>
    ) : (
        <></>
    )
}
