import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'

import { BillingProductV2Type } from '~/types'

import { PayGateMiniLogicProps, payGateMiniLogic } from './payGateMiniLogic'
import { payGateMiniLogicType } from './payGateMiniLogicType'

type UsePayGateButtonReturn = Pick<
    payGateMiniLogicType['values'],
    'ctaLabel' | 'gateVariant' | 'productWithFeature'
> & {
    clickHandlerProps: Pick<LemonButtonProps, 'onClick' | 'to'>
}

function usePayGateButton({
    feature,
    currentUsage,
    onClick,
}: PayGateMiniLogicProps & Pick<LemonButtonProps, 'onClick'>): UsePayGateButtonReturn {
    const { productWithFeature, ctaLink, ctaLabel, gateVariant, isPaymentEntryFlow } = useValues(
        payGateMiniLogic({ feature, currentUsage })
    )
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)

    const clickHandlerProps = isPaymentEntryFlow
        ? {
              onClick: (ev: React.MouseEvent<HTMLButtonElement>) => {
                  startPaymentEntryFlow(
                      productWithFeature as BillingProductV2Type,
                      window.location.pathname + window.location.search
                  )
                  if (onClick) {
                      onClick(ev)
                  }
              },
          }
        : { to: ctaLink }

    return {
        clickHandlerProps,
        ctaLabel,
        gateVariant,
        productWithFeature,
    }
}

type PayGateButtonProps = PayGateMiniLogicProps & Partial<LemonButtonProps>
export const PayGateButton = ({ feature, currentUsage, ...buttonProps }: PayGateButtonProps): JSX.Element | null => {
    const { clickHandlerProps, ctaLabel } = usePayGateButton({ feature, currentUsage, onClick: buttonProps.onClick })

    return (
        <LemonButton type="primary" center {...buttonProps} {...clickHandlerProps}>
            {ctaLabel}
        </LemonButton>
    )
}

type PayGateIconProps = PayGateButtonProps & { icon?: React.ReactElement; disableAutoHide?: boolean }
export const PayGateIcon = ({
    feature,
    currentUsage,
    icon,
    disableAutoHide,
    ...buttonProps
}: PayGateIconProps): JSX.Element | null => {
    const { clickHandlerProps, ctaLabel, gateVariant, productWithFeature } = usePayGateButton({
        feature,
        currentUsage,
        onClick: (ev) => {
            posthog.capture('pay gate icon clicked', {
                product_key: productWithFeature?.type,
                feature: feature,
                gate_variant: gateVariant,
                cta_label: ctaLabel,
            })

            if (buttonProps.onClick) {
                buttonProps.onClick(ev)
            }
        },
    })

    if (!disableAutoHide && !gateVariant) {
        return null
    }

    return (
        <LemonButton
            type="primary"
            center
            icon={icon ?? <IconLock />}
            size="xxsmall"
            tooltip={ctaLabel}
            {...buttonProps}
            {...clickHandlerProps}
        />
    )
}
