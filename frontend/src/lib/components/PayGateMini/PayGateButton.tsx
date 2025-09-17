import { useActions, useValues } from 'kea'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { AddonTrialModal } from './AddonTrialModal'
import { PayGateMiniLogicProps, payGateMiniLogic } from './payGateMiniLogic'

type PayGateButtonProps = PayGateMiniLogicProps & Partial<LemonButtonProps>
export const PayGateButton = ({ feature, currentUsage, ...buttonProps }: PayGateButtonProps): JSX.Element | null => {
    const { productWithFeature, ctaLink, ctaLabel, isPaymentEntryFlow, isTrialFlow, addonTrialModalOpen } = useValues(
        payGateMiniLogic({ feature, currentUsage })
    )
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)
    const { openAddonTrialModal, closeAddonTrialModal } = useActions(payGateMiniLogic({ feature, currentUsage }))

    if (isTrialFlow) {
        return (
            <>
                {productWithFeature && (
                    <AddonTrialModal
                        product={productWithFeature as BillingProductV2AddonType}
                        isOpen={addonTrialModalOpen}
                        onClose={closeAddonTrialModal}
                    />
                )}
                <LemonButton
                    type="primary"
                    center
                    {...buttonProps}
                    onClick={(ev) => {
                        openAddonTrialModal()
                        if (buttonProps.onClick) {
                            buttonProps.onClick(ev)
                        }
                    }}
                    disableClientSideRouting={true}
                >
                    {ctaLabel}
                </LemonButton>
            </>
        )
    }

    if (isPaymentEntryFlow) {
        return (
            <LemonButton
                type="primary"
                center
                {...buttonProps}
                onClick={(ev) => {
                    startPaymentEntryFlow(
                        productWithFeature as BillingProductV2Type,
                        window.location.pathname + window.location.search
                    )
                    if (buttonProps.onClick) {
                        buttonProps.onClick(ev)
                    }
                }}
                disableClientSideRouting={true}
            >
                {ctaLabel}
            </LemonButton>
        )
    }

    return (
        <LemonButton type="primary" center {...buttonProps} to={ctaLink} disableClientSideRouting={isPaymentEntryFlow}>
            {ctaLabel}
        </LemonButton>
    )
}
