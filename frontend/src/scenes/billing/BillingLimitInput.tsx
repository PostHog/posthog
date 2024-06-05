import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useRef } from 'react'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

export const BillingLimitInput = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const limitInputRef = useRef<HTMLInputElement | null>(null)
    const { billing, billingLoading } = useValues(billingLogic)
    const { isEditingBillingLimit, customLimitUsd } = useValues(
        billingProductLogic({ product, billingLimitInputRef: limitInputRef })
    )
    const { setIsEditingBillingLimit, setBillingLimitInput, submitBillingLimitInput } = useActions(
        billingProductLogic({ product })
    )

    if (billing?.billing_period?.interval !== 'month' || !product.subscribed) {
        return null
    }

    return (
        <Form formKey="billingLimitInput" props={{ product: product }} logic={billingProductLogic} enableFormOnSubmit>
            <div className="border-t border-border p-8" data-attr={`billing-limit-input-${product.type}`}>
                <h4 className="my-4">Billing limits</h4>
                <div className="flex">
                    {!isEditingBillingLimit ? (
                        <div className="flex items-center justify-center gap-1">
                            {customLimitUsd ? (
                                <>
                                    <Tooltip title="Set a billing limit to control your recurring costs. Some features may stop working if your usage exceeds your limit.">
                                        <span>
                                            ${customLimitUsd} {billing?.billing_period?.interval}ly billing limit
                                        </span>
                                    </Tooltip>
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
                                    <span>You do not have a billing limit set for {product?.name}.</span>
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
                        <div className="flex items-center justify-center gap-1">
                            <Field name="input" noStyle>
                                {({ value, onChange, error }) => (
                                    <Tooltip title={error}>
                                        <div className="max-w-40">
                                            <LemonInput
                                                ref={limitInputRef}
                                                type="number"
                                                fullWidth={false}
                                                status={error ? 'danger' : 'default'}
                                                value={value}
                                                onChange={onChange}
                                                prefix={<b>$</b>}
                                                disabled={billingLoading}
                                                min={0}
                                                step={10}
                                                suffix={<>/{billing?.billing_period?.interval}</>}
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
                            {customLimitUsd ? (
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
