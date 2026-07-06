import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useRef } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { BillingProductV2Type } from '~/types'

import { isAlertOnlyProduct } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

export const BillingLimit = ({
    product,
    // alertOnly renders the same control but as an *alert threshold* rather than an enforced
    // billing limit. Used for Managed data warehouse storage: storage is never hard-capped on
    // paid plans — crossing the value only triggers an in-app banner + email.
    alertOnly = false,
    // Scopes an enforced limit to one part of a multi-part product (e.g. "compute" on the Managed
    // data warehouse card, where the limit caps compute only — storage is a separate alert-only line).
    scopeName,
}: {
    product: BillingProductV2Type
    alertOnly?: boolean
    scopeName?: string
}): JSX.Element | null => {
    const limitInputRef = useRef<HTMLInputElement | null>(null)
    const { billing, billingLoading } = useValues(billingLogic)
    const { isEditingBillingLimit, customLimitUsd, hasCustomLimitSet, currentAndUpgradePlans, billingLimitNextPeriod } =
        useValues(billingProductLogic({ product, billingLimitInputRef: limitInputRef }))
    const { setIsEditingBillingLimit, setBillingLimitInput, submitBillingLimitInput, removeBillingLimitNextPeriod } =
        useActions(billingProductLogic({ product }))

    const initialBillingLimit = currentAndUpgradePlans?.currentPlan?.initial_billing_limit
    const usingInitialBillingLimit = customLimitUsd === initialBillingLimit

    // Alert-only products (never hard-capped, e.g. MDW storage) — true whether rendered nested
    // under compute (the grouped MDW card) or as their own top-level card. Detect via the product
    // itself instead of relying on the caller passing `alertOnly`, so a consumer that renders the
    // flat `billing.products` list can't surface enforced-limit copy for an alert-only product.
    const isAlertOnly = alertOnly || isAlertOnlyProduct(product)

    // Copy differs for alert-only (storage) vs enforced (everything else). When `scopeName` is set,
    // the enforced-limit copy names that scope (e.g. "Compute billing limit", "set for compute") so
    // it's clear the limit applies only to that part of the product.
    const productLabel = scopeName ?? product?.name?.toLowerCase()
    const heading = isAlertOnly
        ? 'Storage usage alert'
        : scopeName
          ? `${capitalizeFirstLetter(scopeName)} billing limit`
          : 'Billing limit'
    const noun = isAlertOnly ? 'usage alert' : 'billing limit'
    const setLabel = isAlertOnly ? 'Set an alert' : 'Set a billing limit'
    const enforcedTooltip = isAlertOnly
        ? "We'll email you and show an in-app banner when your storage spend reaches this amount. Storage is never blocked — you keep your data."
        : 'Set a billing limit to control your recurring costs. Some features may stop working and data may be dropped if your usage exceeds your limit.'

    if (billing?.billing_period?.interval !== 'month' || !product.subscribed || product.inclusion_only) {
        return null
    }

    return (
        <Form formKey="billingLimitInput" props={{ product: product }} logic={billingProductLogic} enableFormOnSubmit>
            <div
                className="border-t border-primary px-8 py-4"
                data-attr={`billing-limit-input-wrapper-${product.type}`}
            >
                <h4>{heading}</h4>
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
                                            <Tooltip title={enforcedTooltip}>
                                                <span
                                                    className="text-sm"
                                                    data-attr={`billing-limit-set-${product.type}`}
                                                >
                                                    {isAlertOnly ? (
                                                        <>
                                                            We'll alert you when storage spend reaches{' '}
                                                            <b>${customLimitUsd?.toLocaleString()}</b> — storage is
                                                            never blocked.
                                                        </>
                                                    ) : (
                                                        <>
                                                            You have a <b>${customLimitUsd?.toLocaleString()}</b>{' '}
                                                            billing limit set for {productLabel}.
                                                        </>
                                                    )}
                                                </span>
                                            </Tooltip>
                                        )}

                                        <LemonButton
                                            onClick={() => setIsEditingBillingLimit(true)}
                                            status="danger"
                                            size="small"
                                        >
                                            {isAlertOnly ? 'Edit alert' : 'Edit limit'}
                                        </LemonButton>
                                    </>
                                ) : (
                                    <>
                                        <span className="text-sm" data-attr={`billing-limit-not-set-${product.type}`}>
                                            You do not have a {noun} set for {productLabel}.
                                        </span>
                                        <LemonButton
                                            onClick={() => setIsEditingBillingLimit(true)}
                                            status="danger"
                                            size="small"
                                        >
                                            {setLabel}
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
                                        tooltip={isAlertOnly ? 'Remove alert' : 'Remove billing limit'}
                                        onClick={() => {
                                            setBillingLimitInput(null)
                                            submitBillingLimitInput()
                                        }}
                                    >
                                        {isAlertOnly ? 'Remove alert' : 'Remove limit'}
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
