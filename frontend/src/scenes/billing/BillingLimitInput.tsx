import { BillingProductV2AddonType, BillingProductV2Type, BillingV2TierType } from '~/types'
import { billingLogic } from './billingLogic'
import { convertAmountToUsage } from './billing-utils'
import { useActions, useValues } from 'kea'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { billingProductLogic } from './billingProductLogic'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'

export const BillingLimitInput = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { billing, billingLoading } = useValues(billingLogic)
    const { updateBillingLimits } = useActions(billingLogic)
    const { isEditingBillingLimit, showBillingLimitInput, billingLimitInput, customLimitUsd } = useValues(
        billingProductLogic({ product })
    )
    const { setIsEditingBillingLimit, setBillingLimitInput } = useActions(billingProductLogic({ product }))

    const updateBillingLimit = (value: number | undefined): any => {
        const actuallyUpdateLimit = (): void => {
            updateBillingLimits({
                [product.type]: typeof value === 'number' ? `${value}` : null,
            })
        }
        if (value === undefined) {
            return actuallyUpdateLimit()
        }

        const addonTiers = product.addons
            ?.filter((addon: BillingProductV2AddonType) => addon.subscribed)
            ?.map((addon: BillingProductV2AddonType) => addon.tiers)

        const productAndAddonTiers: BillingV2TierType[][] = [product.tiers, ...addonTiers].filter(
            Boolean
        ) as BillingV2TierType[][]

        const newAmountAsUsage = product.tiers
            ? convertAmountToUsage(`${value}`, productAndAddonTiers, billing?.discount_percent)
            : 0

        if (product.current_usage && newAmountAsUsage < product.current_usage) {
            LemonDialog.open({
                title: 'Billing limit warning',
                description:
                    'Your new billing limit will be below your current usage. Your bill will not increase for this period but parts of the product will stop working and data may be lost.',
                primaryButton: {
                    status: 'danger',
                    children: 'I understand',
                    onClick: () => actuallyUpdateLimit(),
                },
                secondaryButton: {
                    children: 'I changed my mind',
                },
            })
            return
        }

        if (product.projected_usage && newAmountAsUsage < product.projected_usage) {
            LemonDialog.open({
                title: 'Billing limit warning',
                description:
                    'Your predicted usage is above your billing limit which is likely to result in usage being throttled.',
                primaryButton: {
                    children: 'I understand',
                    onClick: () => actuallyUpdateLimit(),
                },
                secondaryButton: {
                    children: 'I changed my mind',
                },
            })
            return
        }

        return actuallyUpdateLimit()
    }

    if (!showBillingLimitInput || !product.subscribed) {
        return null
    }
    return (
        <div className="border-t border-border p-8" data-attr={`billing-limit-input-${product.type.replace('_', '-')}`}>
            <div className="flex">
                <div className="flex items-center gap-1">
                    {!isEditingBillingLimit ? (
                        <>
                            <div
                                className={clsx('cursor-pointer', customLimitUsd && 'text-link')}
                                onClick={() => setIsEditingBillingLimit(true)}
                            >
                                ${customLimitUsd}
                            </div>
                            <Tooltip
                                title={
                                    <>
                                        Set a billing limit to control your recurring costs. Some features may stop
                                        working if your usage exceeds your billing cap.
                                    </>
                                }
                            >
                                {billing?.billing_period?.interval}ly billing limit
                            </Tooltip>
                        </>
                    ) : (
                        <>
                            <div className="max-w-40">
                                <LemonInput
                                    type="number"
                                    fullWidth={false}
                                    value={billingLimitInput}
                                    onChange={setBillingLimitInput}
                                    prefix={<b>$</b>}
                                    disabled={billingLoading}
                                    min={0}
                                    step={10}
                                    suffix={<>/{billing?.billing_period?.interval}</>}
                                    size="small"
                                />
                            </div>

                            <LemonButton
                                onClick={() => updateBillingLimit(billingLimitInput)}
                                loading={billingLoading}
                                type="primary"
                                size="small"
                            >
                                Save
                            </LemonButton>
                            <LemonButton
                                onClick={() => setIsEditingBillingLimit(false)}
                                disabled={billingLoading}
                                type="secondary"
                                size="small"
                            >
                                Cancel
                            </LemonButton>
                            {customLimitUsd ? (
                                <LemonButton
                                    // icon={<IconDelete />}
                                    status="danger"
                                    size="small"
                                    tooltip="Remove billing limit"
                                    onClick={() => updateBillingLimit(undefined)}
                                >
                                    Remove limit
                                </LemonButton>
                            ) : null}
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
