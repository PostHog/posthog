import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonModal, Tooltip } from '@posthog/lemon-ui'
import { RefCallback } from 'react'

import { BillingV2PlanType } from '~/types'

type ConfirmUpgradeModalProps = {
    isOpen: boolean
    onSave: () => void
    onClose: () => void
    upgradePlan?: BillingV2PlanType
    overlayRef?: RefCallback<HTMLDivElement>
}

export function ConfirmUpgradeModal({
    isOpen,
    onSave,
    upgradePlan,
    onClose,
    overlayRef,
}: ConfirmUpgradeModalProps): JSX.Element | null {
    if (!upgradePlan) {
        return null
    }

    return (
        <LemonModal
            overlayRef={overlayRef}
            isOpen={isOpen}
            onClose={onClose}
            forceAbovePopovers={true}
            title={`Ready to subscribe to the ${upgradePlan.name}?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={onSave}>
                        Sign me up
                    </LemonButton>
                </>
            }
        >
            <div>
                <p>You'll be charged ${upgradePlan.unit_amount_usd} immediately.</p>

                {upgradePlan.features.length > 1 && (
                    <div>
                        <p className="ml-0 mb-2 max-w-200">Features included:</p>
                        {upgradePlan.features.map((feature, i) => {
                            return (
                                i < 6 && (
                                    <div className="flex gap-x-2 items-center mb-2" key={'addon-features-' + i}>
                                        <IconCheckCircle className="text-success" />
                                        <Tooltip key={feature.key} title={feature.description}>
                                            <b>{feature.name} </b>
                                        </Tooltip>
                                    </div>
                                )
                            )
                        })}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
