import { useActions, useValues } from 'kea'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'

import { BillingProductV2Type } from '~/types'

import { PayGateMiniLogicProps, payGateMiniLogic } from './payGateMiniLogic'

type PayGateButtonProps = PayGateMiniLogicProps & Partial<LemonButtonProps>
export const PayGateButton = ({ feature, currentUsage, ...buttonProps }: PayGateButtonProps): JSX.Element | null => {
    const { productWithFeature, ctaLink, ctaLabel, isPaymentEntryFlow } = useValues(
        payGateMiniLogic({ feature, currentUsage })
    )
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)

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
