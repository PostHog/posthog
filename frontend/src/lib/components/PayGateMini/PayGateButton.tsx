import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { PayGateMiniLogicProps, payGateMiniLogic } from './payGateMiniLogic'
import type { payGateMiniLogicType } from './payGateMiniLogic'

type UsePayGateButtonReturn = Pick<
    payGateMiniLogicType['values'],
    'ctaLabel' | 'ctaDisabledReason' | 'gateVariant' | 'productWithFeature'
> & {
    clickHandlerProps: Pick<LemonButtonProps, 'onClick' | 'to'>
}

function usePayGateButton({
    feature,
    currentUsage,
    onClick,
}: PayGateMiniLogicProps & Pick<LemonButtonProps, 'onClick'>): UsePayGateButtonReturn {
    const logic = payGateMiniLogic({ feature, currentUsage })
    const { productWithFeature, ctaLink, ctaLabel, ctaDisabledReason, gateVariant, isPaymentEntryFlow } =
        useValues(logic)
    const { startPaymentEntryFlow } = useActions(logic)

    const clickHandlerProps = isPaymentEntryFlow
        ? {
              onClick: (ev: React.MouseEvent<HTMLButtonElement>) => {
                  startPaymentEntryFlow()
                  if (onClick) {
                      onClick(ev)
                  }
              },
          }
        : { to: ctaLink }

    return {
        clickHandlerProps,
        ctaLabel,
        ctaDisabledReason,
        gateVariant,
        productWithFeature,
    }
}

type PayGateButtonProps = PayGateMiniLogicProps & Partial<LemonButtonProps>
export const PayGateButton = ({ feature, currentUsage, ...buttonProps }: PayGateButtonProps): JSX.Element | null => {
    const { clickHandlerProps, ctaLabel, ctaDisabledReason } = usePayGateButton({
        feature,
        currentUsage,
        onClick: buttonProps.onClick,
    })

    return (
        <LemonButton
            type="primary"
            center
            {...buttonProps}
            {...clickHandlerProps}
            disabledReason={ctaDisabledReason || buttonProps.disabledReason}
        >
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
    const { clickHandlerProps, ctaLabel, ctaDisabledReason, gateVariant, productWithFeature } = usePayGateButton({
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
            disabledReason={ctaDisabledReason || buttonProps.disabledReason}
        />
    )
}
