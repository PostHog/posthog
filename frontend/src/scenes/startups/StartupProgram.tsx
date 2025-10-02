import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconArrowRight, IconCheck, IconUpload, IconX } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonInput, LemonSelect, Link, Spinner, lemonToast } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { ClimberHog1, ClimberHog2, YCHog } from 'lib/components/hedgehogs'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, ProductKey } from '~/types'

import { RAISED_OPTIONS } from './constants'
import { StartupProgramLogicProps, startupProgramLogic } from './startupProgramLogic'

const YC_DEAL_BOOKFACE = 'https://bookface.ycombinator.com/deals/687'

const BillingUpgradeCTAWrapper: React.FC<{ platformAndSupportProduct: BillingProductV2Type }> = ({
    platformAndSupportProduct,
}) => {
    const { billing } = useValues(billingLogic)
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)
    const { billingProductLoading } = useValues(billingProductLogic({ product: platformAndSupportProduct }))
    return (
        <BillingUpgradeCTA
            type="primary"
            data-attr="startup-program-upgrade-cta"
            disableClientSideRouting
            loading={!!billingProductLoading}
            onClick={() =>
                startPaymentEntryFlow(platformAndSupportProduct, window.location.pathname + window.location.search)
            }
        >
            {billing?.customer_id ? 'Subscribe' : 'Add billing details'}
        </BillingUpgradeCTA>
    )
}

export const scene: SceneExport<StartupProgramLogicProps> = {
    component: StartupProgram,
    logic: startupProgramLogic,
    paramsToProps: ({ params: { referrer } }) => ({ referrer: referrer || undefined }),
}

export function StartupProgram(): JSX.Element {
    const {
        startupProgram,
        formSubmitted,
        isCurrentlyOnStartupPlan,
        wasPreviouslyOnStartupPlan,
        isUserOrganizationOwnerOrAdmin,
        isYC,
        isReferralProgram,
        referrerDisplayName,
        ycBatchOptions,
    } = useValues(startupProgramLogic)
    const { billing, billingLoading, isAnnualPlanCustomer, accountOwner } = useValues(billingLogic)
    const { setStartupProgramValue } = useActions(startupProgramLogic)

    const programName = isYC ? 'YC Program' : 'Startup Program'
    const platformAndSupportProduct = billing?.products?.find(
        (product) => product.type === ProductKey.PLATFORM_AND_SUPPORT
    )

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url) => {
            setStartupProgramValue('yc_proof_screenshot_url', url)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading screenshot: ${detail}`)
            setStartupProgramValue('yc_proof_screenshot_url', undefined)
        },
    })

    if (isCurrentlyOnStartupPlan || wasPreviouslyOnStartupPlan) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="info">
                    <h2 className="mb-2">
                        You {wasPreviouslyOnStartupPlan ? 'were' : 'are'} already in the {programName}
                    </h2>
                    <p>
                        It looks like your organization {wasPreviouslyOnStartupPlan ? 'was' : 'is'} already part of our{' '}
                        {programName}. If you have any questions, please contact our support team.
                    </p>
                    <LemonButton type="primary" to={urls.projectHomepage()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    if (isAnnualPlanCustomer) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="info">
                    <h2 className="mb-2">You are already on an annual plan</h2>
                    <p>
                        It looks like your organization is already on our annual plan. If you have any questions, please
                        contact{' '}
                        {accountOwner?.name && accountOwner?.email
                            ? `your PostHog human ${accountOwner.name.split(' ')[0]} at ${accountOwner.email}`
                            : 'our support team'}
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
                            <div className="relative">
                                <YCHog className="h-auto w-full" />
                            </div>
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
                            <div className="relative w-35 min-w-18">
                                <ClimberHog1 className="h-auto w-full" />
                            </div>
                        </div>
                        <div className="text-center">
                            <h1 className="text-xl sm:text-3xl mb-2 sm:mb-3">
                                {isReferralProgram && referrerDisplayName
                                    ? `PostHog x ${referrerDisplayName}`
                                    : "Apply for PostHog's startup program"}
                            </h1>
                            <p className="text-sm sm:text-base text-muted">
                                Get $50,000 in credits (plus extras you'll actually use) to help you get to
                                product-market fit.
                            </p>
                        </div>
                        <div className="flex items-center">
                            <div className="relative w-35 min-w-18">
                                <ClimberHog2 className="h-auto w-full" />
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <div className="grid md:grid-cols-2 gap-8 mb-8">
                <div className="bg-surface-secondary rounded-lg p-6">
                    <h2 className="text-xl mb-4">
                        {isReferralProgram && referrerDisplayName
                            ? `We've teamed up with ${referrerDisplayName} to offer you`
                            : 'What you can get'}
                    </h2>
                    <div className="space-y-3">
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">
                                    $50,000 in PostHog credit
                                    {isYC && <span className="text-[0.66em] align-super text-muted"> 1</span>}
                                </h4>
                                <p className="text-muted text-sm">Valid for 1 year to use across all products</p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">
                                    Exclusive founder merch
                                    {isYC && <span className="text-[0.66em] align-super text-muted"> 2</span>}
                                </h4>
                                <p className="text-muted text-sm">
                                    Who wouldn't want free laptop stickers, hats, or t-shirts?
                                </p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">50% off Mintlify for 6 months</h4>
                                <p className="text-muted text-sm">So you can build better documentation</p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">50% off Speakeasy for 6 months</h4>
                                <p className="text-muted text-sm">So you can build better APIs, faster</p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">$5,000 in Chroma credit</h4>
                                <p className="text-muted text-sm">Great for building better AI agents</p>
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

                    {isYC && (
                        <div className="mt-4">
                            <div className="text-xs text-muted space-y-1">
                                <div className="flex gap-1">
                                    <span className="text-xxs align-super">1</span>
                                    Applies to current and previous 4 batches. Earlier batches get $25,000 for 12
                                    months.
                                </div>
                                <div className="flex gap-1">
                                    <span className="text-xxs align-super">2</span>
                                    Boring international customs reasons mean users outside US/Canada get a $150 PostHog
                                    merch voucher instead.
                                </div>
                            </div>
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
                                {platformAndSupportProduct && (
                                    <BillingUpgradeCTAWrapper platformAndSupportProduct={platformAndSupportProduct} />
                                )}
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
                                            <LemonSelect options={ycBatchOptions} className="bg-bg-light" />
                                        </LemonField>

                                        <LemonField
                                            name="yc_proof_screenshot_url"
                                            label={
                                                <span>
                                                    Screenshot showing you're using{' '}
                                                    <Link target="_blank" to={YC_DEAL_BOOKFACE}>
                                                        PostHog deal
                                                    </Link>{' '}
                                                    on Bookface
                                                </span>
                                            }
                                            info="Open PostHog deal on Bookface, click 'Mark Using', take a screenshot and attach it below"
                                        >
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
                                                                    YC deal screenshot
                                                                </span>
                                                                <div className="relative">
                                                                    <img
                                                                        src={startupProgram.yc_proof_screenshot_url}
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
                                                                <span>Upload Screenshot</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                }
                                            />
                                        </LemonField>

                                        <LemonField
                                            name="yc_merch_count"
                                            label="How many merch packs do you need for you and your co-founder(s)?"
                                        >
                                            <LemonInput type="number" min={1} max={5} />
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
