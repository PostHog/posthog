import { IconArrowRight, IconCheck, IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, LemonSelect, lemonToast, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { ClimberHog1, ClimberHog2, YCHog } from 'lib/components/hedgehogs'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useEffect } from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { RAISED_OPTIONS, startupProgramLogic, YC_BATCH_OPTIONS } from './startupProgramLogic'

export const scene: SceneExport = {
    component: StartupProgram,
}

export function StartupProgram(): JSX.Element {
    const {
        location: { pathname },
    } = useValues(router)
    const isYC = pathname.endsWith('/yc')

    const logic = startupProgramLogic({ isYC })
    const {
        startupProgram,
        formSubmitted,
        isAlreadyOnStartupPlan,
        isUserOrganizationOwnerOrAdmin,
        ycValidationState,
        ycValidationError,
        verifiedCompanyName,
        startupProgramErrors,
    } = useValues(logic)
    const { billing, billingLoading } = useValues(billingLogic)
    const { validateYCBatch, setStartupProgramValue, showPaymentEntryModal } = useActions(logic)
    const programName = isYC ? 'YC Program' : 'Startup Program'

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url) => {
            setStartupProgramValue('yc_proof_screenshot_url', url)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading screenshot: ${detail}`)
            setStartupProgramValue('yc_proof_screenshot_url', undefined)
        },
    })

    useEffect(() => {
        // eslint-disable-next-line no-console
        console.log('📝 Form values:', startupProgram)
    }, [startupProgram])

    useEffect(() => {
        // eslint-disable-next-line no-console
        console.log('❌ Form errors:', startupProgramErrors)
    }, [startupProgramErrors])

    if (isAlreadyOnStartupPlan) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="info">
                    <h2 className="mb-2">You're already in the {programName}</h2>
                    <p>
                        It looks like your organization is already part of our {programName}. If you have any questions,
                        please contact our support team.
                    </p>
                    <LemonButton type="primary" to={urls.projectHomepage()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    if (!isUserOrganizationOwnerOrAdmin) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="warning">
                    <h2 className="mb-2">Admin or owner permission required</h2>
                    <p>
                        You need to be an organization admin or owner to apply for the startup program. Please contact
                        your organization admin for assistance.
                    </p>
                    <LemonButton type="primary" to={urls.projectHomepage()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="mx-auto max-w-[1200px]">
            <div className="flex flex-col items-center mb-8">
                {isYC ? (
                    <div className="flex flex-col items-center mt-8">
                        <div className="px-4 w-full max-w-100 mb-4">
                            <YCHog className="h-auto" />
                        </div>
                        <div className="text-center">
                            <h1 className="text-2xl sm:text-3xl mb-2 sm:mb-3">
                                You've found our secret Y Combinator offer!
                            </h1>
                            <p className="text-sm sm:text-base text-muted">
                                Get $50,000 in credits (plus extras you'll actually use) to help you get to
                                product-market fit.
                            </p>
                        </div>
                    </div>
                ) : (
                    <div className="flex items-center justify-center -mt-6 md:gap-8 mb-3">
                        <div className="flex items-end self-end">
                            <ClimberHog1 className="w-35 min-w-18 h-auto" />
                        </div>
                        <div className="text-center">
                            <h1 className="text-xl sm:text-3xl mb-2 sm:mb-3">Apply for PostHog's startup program</h1>
                            <p className="text-sm sm:text-base text-muted">
                                Get $50,000 in credits (plus extras you'll actually use) to help you get to
                                product-market fit.
                            </p>
                        </div>
                        <div className="flex items-center">
                            <ClimberHog2 className="w-35 min-w-18 h-auto" />
                        </div>
                    </div>
                )}
            </div>

            <div className="grid md:grid-cols-2 gap-8 mb-8">
                <div className="bg-surface-secondary rounded-lg p-6">
                    <h2 className="text-xl mb-4">What you can get</h2>
                    <div className="space-y-3">
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">$50,000 in PostHog credit</h4>
                                <p className="text-muted text-sm">Valid for 1 year to use across all products</p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">Exclusive founder merch</h4>
                                <p className="text-muted text-sm">
                                    Who wouldn't want free laptop stickers, hats, or t-shirts?
                                </p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">50% off Mintlify for 6 months</h4>
                                <p className="text-muted text-sm">The best products deserve the best documentation</p>
                            </div>
                        </div>
                        {isYC && (
                            <div className="flex items-start">
                                <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                                <div>
                                    <h4 className="font-semibold">Priority support</h4>
                                    <p className="text-muted text-sm">
                                        Direct access to our engineering team for technical support
                                    </p>
                                </div>
                            </div>
                        )}
                    </div>

                    {!isYC && (
                        <div className="mt-6">
                            <h3 className="text-lg mb-3">As long as</h3>
                            <ul className="space-y-2">
                                <li className="flex items-center text-sm">
                                    <IconArrowRight className="text-muted shrink-0 mr-2" />
                                    Your company was founded less than 2 years ago
                                </li>
                                <li className="flex items-center text-sm">
                                    <IconArrowRight className="text-muted shrink-0 mr-2" />
                                    You've raised less than $5 million in funding
                                </li>
                            </ul>
                        </div>
                    )}
                </div>

                <div className="space-y-4">
                    {/* Step 1: Add billing details */}
                    <div className="bg-surface-secondary rounded-lg p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-xl m-0">Step 1: Add billing details</h2>
                        </div>
                        {billingLoading ? (
                            <div className="flex items-center gap-2">
                                <Spinner className="text-lg" />
                                <span>Checking if you're on a paid plan</span>
                            </div>
                        ) : billing?.has_active_subscription ? (
                            <div className="flex items-center gap-2 text-success">
                                <IconCheck className="shrink-0" />
                                <span>You're on a paid plan</span>
                            </div>
                        ) : (
                            <div className="flex flex-col items-start gap-2">
                                <p className="text-muted mb-2">
                                    To be eligible for the startup program, you need to be on a paid plan.
                                </p>
                                <p className="text-muted mb-2">
                                    Don't worry - you'll only pay for what you use and can set billing limits as low as
                                    $0 to control your spend.
                                </p>
                                <p className="text-muted mb-2 italic">
                                    P.S. You still keep the monthly free allowance for every product!
                                </p>
                                <BillingUpgradeCTA
                                    type="primary"
                                    data-attr="startup-program-upgrade-cta"
                                    disableClientSideRouting
                                    onClick={() => showPaymentEntryModal()}
                                >
                                    Add billing details
                                </BillingUpgradeCTA>
                            </div>
                        )}
                    </div>

                    {/* Step 2: Submit application form */}
                    <div className="bg-surface-secondary rounded-lg p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-xl m-0">Step 2: Submit application</h2>
                        </div>

                        {formSubmitted ? (
                            <div className="space-y-4">
                                <div className="flex items-center gap-2 text-success">
                                    <IconCheck className="shrink-0" />
                                    <span>Application submitted successfully!</span>
                                </div>
                                <p className="text-muted">
                                    Thank you for your application! We'll review it and get back to you as soon as
                                    possible. In the meantime, you can continue using PostHog.
                                </p>
                                <LemonButton type="primary" to={urls.projectHomepage()}>
                                    Return to PostHog
                                </LemonButton>
                            </div>
                        ) : (
                            <Form
                                logic={startupProgramLogic}
                                props={{ isYC }}
                                formKey="startupProgram"
                                enableFormOnSubmit
                                className="space-y-3"
                            >
                                <div className="hidden">
                                    <div className="grid md:grid-cols-2 gap-3">
                                        <LemonField name="first_name" label="First name">
                                            <LemonInput placeholder="Jane" />
                                        </LemonField>

                                        <LemonField name="last_name" label="Last name">
                                            <LemonInput placeholder="Doe" />
                                        </LemonField>
                                    </div>

                                    <LemonField name="email" label="Email">
                                        <LemonInput placeholder="you@example.com" />
                                    </LemonField>

                                    <LemonField name="startup_domain" label="Company domain">
                                        <LemonInput placeholder="example.com" />
                                    </LemonField>
                                </div>

                                <LemonField
                                    name="organization_name"
                                    label="PostHog organization"
                                    info="To apply for a different organization, switch to that organization first"
                                >
                                    <LemonInput placeholder="Your PostHog organization" disabled />
                                </LemonField>

                                <LemonField name="organization_id" className="hidden">
                                    <LemonInput />
                                </LemonField>

                                {!isYC && (
                                    <>
                                        <LemonField
                                            name="raised"
                                            label="How much in total funding have you raised (USD)"
                                        >
                                            <LemonSelect options={RAISED_OPTIONS} className="bg-bg-light" />
                                        </LemonField>

                                        <LemonField
                                            name="incorporation_date"
                                            label="The date that your company was incorporated"
                                        >
                                            <LemonCalendarSelectInput
                                                clearable={false}
                                                format="YYYY-MM-DD"
                                                buttonProps={{ className: 'bg-bg-light' }}
                                                placeholder=" "
                                                selectionPeriod="past"
                                            />
                                        </LemonField>
                                    </>
                                )}

                                {isYC && (
                                    <>
                                        <LemonField name="yc_batch" label="Which YC batch are you?">
                                            <LemonSelect
                                                options={YC_BATCH_OPTIONS}
                                                onChange={(value) => {
                                                    setStartupProgramValue('yc_batch', value)
                                                    if (value) {
                                                        validateYCBatch()
                                                    }
                                                }}
                                                className="bg-bg-light"
                                            />
                                        </LemonField>
                                        {ycValidationState === 'validating' && (
                                            <div className="flex items-center gap-2 text-muted">
                                                <div className="animate-spin">⏳</div>
                                                <span>Validating YC batch membership...</span>
                                            </div>
                                        )}
                                        {ycValidationState === 'valid' && (
                                            <div className="flex items-center gap-2 text-success">
                                                <IconCheck className="shrink-0" />
                                                <span>
                                                    We were able to confirm your YC membership
                                                    {verifiedCompanyName && ` for ${verifiedCompanyName}`}!
                                                </span>
                                            </div>
                                        )}
                                        {ycValidationState === 'invalid' && (
                                            <>
                                                {!startupProgram.yc_proof_screenshot_url && (
                                                    <div className="flex items-center gap-2 text-danger mb-2">
                                                        {ycValidationError}
                                                    </div>
                                                )}
                                                <LemonField name="yc_proof_screenshot_url">
                                                    <LemonFileInput
                                                        accept="image/*"
                                                        multiple={false}
                                                        value={filesToUpload}
                                                        showUploadedFiles={false}
                                                        onChange={setFilesToUpload}
                                                        loading={uploading}
                                                        callToAction={
                                                            <div className="border border-dashed rounded p-2 w-full">
                                                                {startupProgram.yc_proof_screenshot_url ? (
                                                                    <div className="flex items-center justify-center gap-4 w-full">
                                                                        <span className="font-semibold">
                                                                            YC profile screenshot
                                                                        </span>
                                                                        <div className="relative">
                                                                            <img
                                                                                src={
                                                                                    startupProgram.yc_proof_screenshot_url as string
                                                                                }
                                                                                alt="YC Profile"
                                                                                className="h-10 w-10 rounded object-cover"
                                                                            />
                                                                            <LemonButton
                                                                                type="tertiary"
                                                                                status="danger"
                                                                                size="xsmall"
                                                                                icon={<IconX className="text-sm" />}
                                                                                onClick={(e) => {
                                                                                    e.preventDefault()
                                                                                    setStartupProgramValue(
                                                                                        'yc_proof_screenshot_url',
                                                                                        undefined
                                                                                    )
                                                                                }}
                                                                                tooltip="Remove screenshot"
                                                                                className="absolute -top-1 -right-1 p-0.5 !bg-bg-light rounded-full"
                                                                                noPadding
                                                                            />
                                                                        </div>
                                                                    </div>
                                                                ) : (
                                                                    <div className="flex items-center justify-center gap-2">
                                                                        <IconUpload className="text-2xl" />
                                                                        <span>Upload YC Profile Screenshot</span>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        }
                                                    />
                                                </LemonField>
                                            </>
                                        )}
                                        <LemonField
                                            name="yc_merch_count"
                                            label="How many merch packs do you need for you and your co-founder(s)?"
                                        >
                                            <LemonInput type="number" min={0} max={5} />
                                        </LemonField>
                                    </>
                                )}

                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    className="mt-4"
                                    data-attr="startup-program-submit"
                                >
                                    Submit Application
                                </LemonButton>

                                {/* This will display a form error if user is not on a paid plan. Kea forms requires a child element */}
                                <LemonField name="_form">
                                    <span />
                                </LemonField>
                            </Form>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}

export default StartupProgram
