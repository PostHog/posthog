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

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingProductV2Type, StartupProgramLabel } from '~/types'

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
        isAdminOrOwner,
        isYC,
        isReferralProgram,
        referrerDisplayName,
        ycBatchOptions,
        currentStartupProgramLabel,
    } = useValues(startupProgramLogic)
    const { billing, billingLoading, isAnnualPlanCustomer, accountOwner } = useValues(billingLogic)
    const { setStartupProgramValue } = useActions(startupProgramLogic)

    const currentProgramName = currentStartupProgramLabel === StartupProgramLabel.YC ? 'YC Program' : 'Startup Program'
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

    // Show early return banner only for non-YC pages when already on a plan
    // For YC pages, we show the full page with a status box instead
    if (isCurrentlyOnStartupPlan && !isYC) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="info">
                    <h2 className="mb-2">You are already in the {currentProgramName}</h2>
                    <p>It looks like your organization is already part of our {currentProgramName}.</p>
                    {currentStartupProgramLabel === StartupProgramLabel.YC && (
                        <p>
                            Your credits will renew automatically{' '}
                            <span className="font-semibold">every year, forever.</span>
                        </p>
                    )}
                    <p>If you have any questions, please contact our support team.</p>
                    <LemonButton type="primary" to={urls.projectRoot()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    // YC customers can re-apply
    if (wasPreviouslyOnStartupPlan && !isYC) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="info">
                    <h2 className="mb-2">You were already in the Startup Program</h2>
                    <p>
                        It looks like your organization was already part of our Startup Program. If you have any
                        questions, please contact our support team.
                    </p>
                    <LemonButton type="primary" to={urls.projectRoot()} className="mt-2">
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
                    <LemonButton type="primary" to={urls.projectRoot()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    if (!isAdminOrOwner) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="warning">
                    <h2 className="mb-2">Admin or owner permission required</h2>
                    <p>
                        You need to be an organization admin or owner to apply for the startup program. Please contact
                        your organization admin for assistance.
                    </p>
                    <LemonButton type="primary" to={urls.projectRoot()} className="mt-2">
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
                                Get $50,000 in credits <span className="font-semibold">every. year. forever.</span>{' '}
                                (plus extras you'll actually use) to help you get to product-market fit.
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
                                    $50,000 in PostHog credit{}
                                    {isYC && (
                                        <>
                                            {' '}
                                            every. year. forever.
                                            <span className="text-[0.66em] align-super text-muted"> 1</span>
                                        </>
                                    )}
                                </h4>
                                <p className="text-muted text-sm">
                                    {isYC
                                        ? 'Valid to use across all products'
                                        : 'Valid for 1 year to use across all products'}
                                </p>
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
                                    Credits renew automatically each year. If you've previously been in the program and
                                    your credits expired, you can reapply and continue getting $50,000 annually.
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
                    {/* Show status box for current startup plan customers visiting YC page */}
                    {isCurrentlyOnStartupPlan && isYC ? (
                        <div className="bg-surface-secondary rounded-lg p-6">
                            <div className="flex items-center gap-2 mb-4">
                                <IconCheck className="text-success shrink-0 size-6" />
                                <h2 className="text-xl m-0">You're in the {currentProgramName}</h2>
                            </div>
                            {currentStartupProgramLabel === StartupProgramLabel.YC ? (
                                <p>
                                    Your credits will renew automatically{' '}
                                    <span className="font-semibold">every year, forever.</span>
                                </p>
                            ) : (
                                <p>
                                    If you qualify for the YC Program and your Startup Program credits expire, you can
                                    reapply for the YC deal and receive $50,000 in credits annually.
                                </p>
                            )}
                            <p className="mt-2">If you have any questions, please contact our support team.</p>
                            <LemonButton type="primary" to={urls.projectRoot()} className="mt-4">
                                Return to PostHog
                            </LemonButton>
                        </div>
                    ) : (
                        <>
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
                                            Don't worry - you'll only pay for what you use and can set billing limits as
                                            low as $0 to control your spend.
                                        </p>
                                        <p className="text-muted mb-2 italic">
                                            P.S. You still keep the monthly free allowance for every product!
                                        </p>
                                        {platformAndSupportProduct && (
                                            <BillingUpgradeCTAWrapper
                                                platformAndSupportProduct={platformAndSupportProduct}
                                            />
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Step 2: Submit application form */}
                            <div className="bg-surface-secondary rounded-lg p-6">
                                <div className="flex items-center justify-between mb-4">
                                    <h2 className="text-xl m-0">Step 2: Submit application</h2>
                                </div>

                                {/* Show reapplication banner for YC users who were previously in a program */}
                                {wasPreviouslyOnStartupPlan && isYC && (
                                    <LemonBanner type="info" className="mb-4">
                                        <p>
                                            You can reapply for the YC Program and receive $50,000 in credits annually,
                                            renewed each year.
                                        </p>
                                    </LemonBanner>
                                )}

                                {formSubmitted ? (
                                    <div className="space-y-4">
                                        <div className="flex items-center gap-2 text-success">
                                            <IconCheck className="shrink-0" />
                                            <span>Application submitted successfully!</span>
                                        </div>
                                        <p className="text-muted">
                                            Thank you for your application! We'll review it and get back to you as soon
                                            as possible. In the meantime, you can continue using PostHog.
                                        </p>
                                        <LemonButton type="primary" to={urls.projectRoot()}>
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
                                                                                src={
                                                                                    startupProgram.yc_proof_screenshot_url
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
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}

export default StartupProgram
