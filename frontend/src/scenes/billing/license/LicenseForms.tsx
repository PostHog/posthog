import React from 'react'
import { useValues, useActions } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { Form } from 'kea-forms'
import { LemonCheckbox, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import { Field } from 'lib/forms/Field'
import { licenseLogic } from 'scenes/instance/Licenses/licenseLogic'

export function LicenseForms(): JSX.Element {
    const { isActivateLicenseSubmitting, showLicenseDirectInput } = useValues(licenseLogic)
    const { setShowLicenseDirectInput } = useActions(licenseLogic)

    return (
        <div className="border rounded p-8 shadow" style={{ minWidth: 500 }}>
            {showLicenseDirectInput ? (
                <>
                    <h2 className="text-center">Activate a PostHog license key</h2>
                    <Form logic={licenseLogic} formKey="activateLicense" enableFormOnSubmit className="space-y-4">
                        <Field name="key" label={'License key'}>
                            <LemonInput fullWidth />
                        </Field>

                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isActivateLicenseSubmitting}
                            fullWidth
                            center
                            size="large"
                        >
                            Activate license key
                        </LemonButton>
                    </Form>
                </>
            ) : (
                <>
                    <h2 className="text-center">Get a PostHog license key</h2>
                    <Form logic={licenseLogic} formKey="createLicense" enableFormOnSubmit className="space-y-4">
                        <Field name="client_name" label="Company Name">
                            <LemonInput fullWidth />
                        </Field>

                        <Field
                            name="billing_email"
                            label="Billing Email"
                            help="Your license key will also be sent to this email address"
                        >
                            <LemonInput fullWidth />
                        </Field>

                        <Field name="terms">
                            <LemonCheckbox
                                bordered
                                fullWidth
                                label={
                                    <>
                                        I accept the{' '}
                                        <Link target="_blank" to="https://posthog.com/terms">
                                            terms and conditions
                                        </Link>
                                    </>
                                }
                            />
                        </Field>

                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isActivateLicenseSubmitting}
                            fullWidth
                            center
                            size="large"
                        >
                            Continue to verify card
                        </LemonButton>
                    </Form>
                </>
            )}

            <LemonDivider dashed className="my-4" />

            <LemonButton fullWidth center onClick={() => setShowLicenseDirectInput(!showLicenseDirectInput)}>
                {!showLicenseDirectInput ? 'I already have a license key' : "I don't have a license key"}
            </LemonButton>
        </div>
    )
}
