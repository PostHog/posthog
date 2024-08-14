import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useRef } from 'react'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

export const BillingLimit = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const limitInputRef = useRef<HTMLInputElement | null>(null)
    const { billing, billingLoading } = useValues(billingLogic)
    const { isEditingBillingLimit, customLimitUsd, currentAndUpgradePlans } = useValues(
        billingProductLogic({ product, billingLimitInputRef: limitInputRef })
    )
    const { setIsEditingBillingLimit, setBillingLimitInput, submitBillingLimitInput } = useActions(
        billingProductLogic({ product })
    )

    const initialBillingLimit = currentAndUpgradePlans?.currentPlan?.initial_billing_limit
    const usingInitialBillingLimit = customLimitUsd === initialBillingLimit

    if (billing?.billing_period?.interval !== 'month' || !product.subscribed || product.inclusion_only) {
        return null
    }

    const hasCustomLimit = customLimitUsd === 0 || customLimitUsd
    return (
        <Form formKey="billingLimitInput" props={{ product: product }} logic={billingProductLogic} enableFormOnSubmit>
            <div className="border-t border-border p-8" data-attr={`billing-limit-input-${product.type}`}>
                <h4 className="mb-2">Billing limit</h4>
                <div className="flex">
                    {!isEditingBillingLimit ? (
                        <div className="flex items-center justify-center gap-1">
                            {hasCustomLimit ? (
                                <>
                                    {usingInitialBillingLimit ? (
                                        <Tooltip title="Initial limits protect you from accidentally incurring large unexpected charges. Some features may stop working and data may be dropped if your usage exceeds your limit.">
                                            <span className="text-sm">
                                                This product has a default initial billing limit of{' '}
                                                <b>${initialBillingLimit}</b>.
                                            </span>
                                        </Tooltip>
                                    ) : (
                                        <Tooltip title="Set a billing limit to control your recurring costs. Some features may stop working and data may be dropped if your usage exceeds your limit.">
                                            <span className="text-sm">
                                                You have a <b>${customLimitUsd}</b> billing limit set for{' '}
                                                {product?.name?.toLowerCase()}.
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
                                    <span className="text-sm">
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
                            )}{' '}
                        </div>
                    ) : (
                        <div className="flex items-center justify-center gap-2.5">
                            <Field name="input" noStyle>
                                {({ value, onChange, error }) => (
                                    <Tooltip title={error}>
                                        <div className="max-w-36">
                                            <LemonInput
                                                inputRef={limitInputRef}
                                                type="number"
                                                fullWidth={false}
                                                status={error ? 'danger' : 'default'}
                                                value={value}
                                                onChange={onChange}
                                                prefix={<b>$</b>}
                                                disabled={billingLoading}
                                                min={0}
                                                step={10}
                                                suffix={<>/ {billing?.billing_period?.interval}</>}
                                                size="small"
                                            />
                                        </div>
                                    </Tooltip>
                                )}
                            </Field>

                            <LemonButton loading={billingLoading} type="primary" size="small" htmlType="submit">
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
                            {hasCustomLimit ? (
                                <LemonButton
                                    status="danger"
                                    size="small"
                                    tooltip="Remove billing limit"
                                    onClick={() => {
                                        setBillingLimitInput(undefined)
                                        submitBillingLimitInput()
                                    }}
                                >
                                    Remove limit
                                </LemonButton>
                            ) : null}
                        </div>
                    )}
                </div>
            </div>
        </Form>
    )
}
