import React, { useState } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { billingLogic } from './billingLogic'
import { LemonButton, LemonDivider, LemonInput, LemonModal, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonDialog } from 'lib/components/LemonDialog'

export function BillingV2(): JSX.Element {
    const { billing, billingLoading, isActivateLicenseSubmitting, showLicenseDirectInput } = useValues(billingLogic)
    const { setShowLicenseDirectInput } = useActions(billingLogic)

    if (!billing && billingLoading) {
        return <SpinnerOverlay />
    }

    return (
        <div>
            <PageHeader title="Billing &amp; usage" />

            {!billing && !billingLoading ? (
                <AlertMessage type="error">
                    There was an issue retreiving your current billing information. If this message persists please
                    contact support.
                </AlertMessage>
            ) : (
                <div className="flex">
                    <div className="flex-1">
                        <p>Paying is good because money is good 👍</p>
                    </div>

                    <LemonDivider vertical dashed />

                    <div className="p-4 space-y-2" style={{ width: '20rem' }}>
                        {billing?.subscription_url ? (
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                to={billing.subscription_url}
                                disableClientSideRouting
                                fullWidth
                                center
                            >
                                Manage subscription
                            </LemonButton>
                        ) : showLicenseDirectInput ? (
                            <>
                                <Form
                                    logic={billingLogic}
                                    formKey="activateLicense"
                                    enableFormOnSubmit
                                    className="space-y-4"
                                >
                                    <Field name="license" label={'Activate license key'}>
                                        <LemonInput fullWidth autoFocus />
                                    </Field>

                                    <LemonButton
                                        type="primary"
                                        htmlType="submit"
                                        loading={isActivateLicenseSubmitting}
                                        fullWidth
                                        center
                                    >
                                        Activate license key
                                    </LemonButton>
                                </Form>
                            </>
                        ) : (
                            <>
                                <LemonButton
                                    to="/api/billing-v2/activation"
                                    type="primary"
                                    size="large"
                                    fullWidth
                                    center
                                    disableClientSideRouting
                                >
                                    Setup payment
                                </LemonButton>
                            </>
                        )}

                        {!billing ? (
                            <LemonButton
                                fullWidth
                                center
                                onClick={() => setShowLicenseDirectInput(!showLicenseDirectInput)}
                            >
                                {!showLicenseDirectInput
                                    ? 'I already have a license key'
                                    : "I don't have a license key"}
                            </LemonButton>
                        ) : null}
                    </div>
                </div>
            )}

            <LemonDivider dashed className="my-2" />
            <BillingProduct />
            <LemonDivider dashed className="my-2" />
            <BillingProduct />
        </div>
    )
}

const BillingProduct = (): JSX.Element => {
    const [showBillingLimit, setShowBillingLimit] = useState(false)

    const onBillingLimitToggle = (): void => {
        if (!showBillingLimit) {
            return setShowBillingLimit(true)
        }
        LemonDialog.open({
            title: 'Remove billing limit',
            description:
                'Your predicted usage is above your current billing limit which is likely to result in a bill. Are you sure you want to remove the limit?',
            primaryButton: {
                children: 'Yes, remove the limit',
                onClick: () => setShowBillingLimit(false),
            },
            secondaryButton: {
                children: 'I changed my mind',
            },
        })
    }
    return (
        <div className="flex">
            <div className="flex-1 py-4 pr-2 space-y-4">
                <div className="flex justify-between items-start">
                    <div>
                        <h3>Product OS</h3>
                        <p>Event Pipelines, data warehouse, APIs</p>
                    </div>
                    <div className="space-y-2 flex flex-col items-end">
                        <LemonSwitch
                            checked={showBillingLimit}
                            label="Set billing limit"
                            onChange={onBillingLimitToggle}
                        />
                        {showBillingLimit ? (
                            <div className="flex items-center gap-2" style={{ width: 200 }}>
                                <LemonInput type="number" fullWidth={false} placeholder={'0'} />
                                <span>$/month</span>
                            </div>
                        ) : null}
                    </div>
                </div>

                <div className="">
                    <div className="rounded-lg bg-border-light h-4">
                        <div className="rounded-lg bg-success h-4 w-1/3" />
                    </div>
                </div>
                <div className="flex gap-2">
                    <span>Current bill:</span>
                    <span className="font-bold">$1000</span>
                </div>
                <div className="flex gap-2">
                    <span>Predicted bill :</span>
                    <span className="font-bold">$12000</span>
                </div>
            </div>

            <LemonDivider vertical dashed />

            <div className="p-4 space-y-2 text-xs" style={{ width: '20rem' }}>
                <h4>Pricing breakdown</h4>
                <ul>
                    <li className="flex justify-between border-b border-dashed py-2">
                        <span>First 1 million events/mo</span>
                        <b>Free</b>
                    </li>
                    <li className="flex justify-between border-b border-dashed py-2">
                        <span>1-2 million</span>
                        <b>$0.00045</b>
                    </li>
                    <li className="flex justify-between border-b border-dashed py-2">
                        <span>2-10 million</span>
                        <b>$0.000225</b>
                    </li>
                    <li className="flex justify-between border-b border-dashed py-2">
                        <span>10-100 million</span>
                        <b>$0.000075</b>
                    </li>
                    <li className="flex justify-between py-2">
                        <span>100 million - 1 billion</span>
                        <b>$0.000025</b>
                    </li>
                </ul>
            </div>
        </div>
    )
}
