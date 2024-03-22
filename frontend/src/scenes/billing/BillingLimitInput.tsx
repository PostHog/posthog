import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
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
    const { isEditingBillingLimit, showBillingLimitInput, customLimitUsd } = useValues(
        billingProductLogic({ product, billingLimitInputRef: limitInputRef })
    )
    const { setIsEditingBillingLimit, setBillingLimitInput, submitBillingLimitInput } = useActions(
        billingProductLogic({ product })
    )

    if (!showBillingLimitInput || !product.subscribed) {
        return null
    }
    return (
        <Form formKey="billingLimitInput" props={{ product: product }} logic={billingProductLogic} enableFormOnSubmit>
            <div className="border-t border-border p-8" data-attr={`billing-limit-input-${product.type}`}>
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
                                <Tooltip title="Set a billing limit to control your recurring costs. Some features may stop working if your usage exceeds your limit.">
                                    <span>{billing?.billing_period?.interval}ly billing limit</span>
                                </Tooltip>
                            </>
                        ) : (
                            <>
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
                            </>
                        )}
                    </div>
                </div>
            </div>
        </Form>
    )
}
