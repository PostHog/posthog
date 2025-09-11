import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useRef } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

export const BillingLimit = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const limitInputRef = useRef<HTMLInputElement | null>(null)
    const { billing, billingLoading } = useValues(billingLogic)
    const { isEditingBillingLimit, customLimitUsd, hasCustomLimitSet, currentAndUpgradePlans, billingLimitNextPeriod } =
        useValues(billingProductLogic({ product, billingLimitInputRef: limitInputRef }))
    const { setIsEditingBillingLimit, setBillingLimitInput, submitBillingLimitInput, removeBillingLimitNextPeriod } =
        useActions(billingProductLogic({ product }))

    const initialBillingLimit = currentAndUpgradePlans?.currentPlan?.initial_billing_limit
    const usingInitialBillingLimit = customLimitUsd === initialBillingLimit

    if (billing?.billing_period?.interval !== 'month' || !product.subscribed || product.inclusion_only) {
        return null
    }

    return (
        <Form formKey="billingLimitInput" props={{ product: product }} logic={billingProductLogic} enableFormOnSubmit>
            <div
                className="border-t border-primary px-8 py-4"
                data-attr={`billing-limit-input-wrapper-${product.type}`}
            >
                <h4>Billing limit</h4>
                <div className="flex flex-col xl:flex-row w-full items-stretch xl:items-center justify-start xl:justify-between gap-2">
                    <div className="flex items-center gap-1">
                        {!isEditingBillingLimit ? (
                            <>
                                {hasCustomLimitSet ? (
                                    <>
                                        {usingInitialBillingLimit ? (
                                            <Tooltip title="Initial limits protect you from accidentally incurring large unexpected charges. Some features may stop working and data may be dropped if your usage exceeds your limit.">
                                                <span
                                                    className="text-sm"
                                                    data-attr={`default-billing-limit-${product.type}`}
                                                >
                                                    This product has a default initial billing limit of{' '}
                                                    <b>${initialBillingLimit}</b>.
                                                </span>
                                            </Tooltip>
                                        ) : (
                                            <Tooltip title="Set a billing limit to control your recurring costs. Some features may stop working and data may be dropped if your usage exceeds your limit.">
                                                <span
                                                    className="text-sm"
                                                    data-attr={`billing-limit-set-${product.type}`}
                                                >
                                                    You have a <b>${customLimitUsd?.toLocaleString()}</b> billing limit
                                                    set for {product?.name?.toLowerCase()}.
                                                </span>
                                            </Tooltip>
                                        )}

                                        <LemonButton
                                            onClick={() => setIsEditingBillingLimit(true)}
                                            status="danger"
                                            size="small"
                                        >
                                            Edit limit
                                        </LemonButton>
                                    </>
                                ) : (
                                    <>
                                        <span className="text-sm" data-attr={`billing-limit-not-set-${product.type}`}>
                                            You do not have a billing limit set for {product?.name?.toLowerCase()}.
                                        </span>
                                        <LemonButton
                                            onClick={() => setIsEditingBillingLimit(true)}
                                            status="danger"
                                            size="small"
                                        >
                                            Set a billing limit
                                        </LemonButton>
                                    </>
                                )}
                            </>
                        ) : (
                            <div className="flex items-start justify-start gap-2.5">
                                <LemonField name="input" className="max-w-52">
                                    {({ value, onChange, error }) => (
                                        <LemonInput
                                            inputRef={limitInputRef}
                                            type="number"
                                            fullWidth={false}
                                            status={error ? 'danger' : 'default'}
                                            value={value}
                                            data-attr={`billing-limit-input-${product.type}`}
                                            onChange={onChange}
                                            prefix={<b>$</b>}
                                            disabled={billingLoading}
                                            min={0}
                                            step={1}
                                            suffix={<>/ {billing?.billing_period?.interval}</>}
                                            size="small"
                                        />
                                    )}
                                </LemonField>

                                <LemonButton
                                    loading={billingLoading}
                                    type="primary"
                                    size="small"
                                    htmlType="submit"
                                    data-attr={`save-billing-limit-${product.type}`}
                                >
                                    Save
                                </LemonButton>
                                <LemonButton
                                    onClick={() => {
                                        setIsEditingBillingLimit(false)
                                    }}
                                    disabled={billingLoading}
                                    type="secondary"
                                    size="small"
                                >
                                    Cancel
                                </LemonButton>
                                {hasCustomLimitSet ? (
                                    <LemonButton
                                        status="danger"
                                        size="small"
                                        data-attr={`remove-billing-limit-${product.type}`}
                                        tooltip="Remove billing limit"
                                        onClick={() => {
                                            setBillingLimitInput(null)
                                            submitBillingLimitInput()
                                        }}
                                    >
                                        Remove limit
                                    </LemonButton>
                                ) : null}
                            </div>
                        )}
                    </div>
                    {billingLimitNextPeriod ? (
                        <div className="flex items-center gap-1">
                            <span className="text-sm xl:text-right">
                                Your limit for next period: <b>${billingLimitNextPeriod.toLocaleString()}</b>.
                            </span>
                            <LemonButton
                                size="small"
                                status="danger"
                                onClick={() => removeBillingLimitNextPeriod(product.type)}
                                data-attr={`remove-billing-limit-next-period-${product.type}`}
                            >
                                Remove limit for next period
                            </LemonButton>
                        </div>
                    ) : null}
                </div>
            </div>
        </Form>
    )
}
