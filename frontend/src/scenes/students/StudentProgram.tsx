import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { ClimberHog1, ClimberHog2 } from 'lib/components/hedgehogs'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingProductV2Type } from '~/types'

import { studentProgramLogic } from './studentProgramLogic'

const BillingUpgradeCTAWrapper: React.FC<{ platformAndSupportProduct: BillingProductV2Type }> = ({
    platformAndSupportProduct,
}) => {
    const { billing } = useValues(billingLogic)
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)
    const { billingProductLoading } = useValues(billingProductLogic({ product: platformAndSupportProduct }))
    return (
        <BillingUpgradeCTA
            type="primary"
            data-attr="student-program-upgrade-cta"
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

export const scene: SceneExport = {
    component: StudentProgram,
    logic: studentProgramLogic,
}

export function StudentProgram(): JSX.Element {
    const { formSubmitted, isCurrentlyOnProgram, wasPreviouslyOnProgram, currentProgramLabel, isAdminOrOwner } =
        useValues(studentProgramLogic)
    const { billing, billingLoading, isAnnualPlanCustomer, accountOwner } = useValues(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const platformAndSupportProduct = billing?.products?.find(
        (product) => product.type === ProductKey.PLATFORM_AND_SUPPORT
    )

    // Hide the page entirely until the billing service supports student applications
    if (!featureFlags[FEATURE_FLAGS.STUDENT_PROGRAM_INTENT]) {
        return <NotFound object="page" />
    }

    if (isCurrentlyOnProgram) {
        return (
            <div className="mx-auto w-full max-w-200 mt-6 px-4">
                <LemonBanner type="info">
                    <h2 className="mb-2">You are already in the {currentProgramLabel} program</h2>
                    <p>
                        Your organization is already part of a PostHog credit program, so it can't apply for the student
                        program.
                    </p>
                    <p>If you have any questions, please contact our support team.</p>
                    <LemonButton type="primary" to={urls.projectRoot()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

    if (wasPreviouslyOnProgram) {
        return (
            <div className="mx-auto w-full max-w-200 mt-6 px-4">
                <LemonBanner type="info">
                    <h2 className="mb-2">Your organization was already in a credit program</h2>
                    <p>
                        Organizations that have already used a PostHog credit program aren't eligible for the student
                        program. If you have any questions, please contact our support team.
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
            <div className="mx-auto w-full max-w-200 mt-6 px-4">
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
            <div className="mx-auto w-full max-w-200 mt-6 px-4">
                <LemonBanner type="warning">
                    <h2 className="mb-2">Admin or owner permission required</h2>
                    <p>
                        You need to be an organization admin or owner to apply for the student program. Please contact
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
                <div className="flex items-center justify-center -mt-6 md:gap-8 mb-3">
                    <div className="flex items-end self-end">
                        <div className="relative w-35 min-w-18">
                            <ClimberHog1 className="h-auto w-full" />
                        </div>
                    </div>
                    <div className="text-center">
                        <h1 className="text-xl sm:text-3xl mb-2 sm:mb-3">Apply for PostHog's student program</h1>
                        <p className="text-sm sm:text-base text-muted">
                            Get $50,000 in credits to use across PostHog products while you study.
                        </p>
                    </div>
                    <div className="flex items-center">
                        <div className="relative w-35 min-w-18">
                            <ClimberHog2 className="h-auto w-full" />
                        </div>
                    </div>
                </div>
            </div>

            <div className="grid md:grid-cols-2 gap-8 mb-8">
                <div className="bg-surface-secondary rounded-lg p-6">
                    <h2 className="text-xl mb-4">What you can get</h2>
                    <div className="space-y-3">
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">$50,000 in PostHog credit</h4>
                                <p className="text-muted text-sm">Valid for 1 year</p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">Works across PostHog products</h4>
                                <p className="text-muted text-sm">
                                    Product analytics, session replay, feature flags, error tracking, and more
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="mt-6">
                        <h3 className="text-lg mb-3">As long as</h3>
                        <ul className="space-y-2">
                            <li className="flex items-center text-sm">
                                <IconCheck className="text-muted shrink-0 mr-2" />
                                You're currently enrolled at a university or college
                            </li>
                            <li className="flex items-center text-sm">
                                <IconCheck className="text-muted shrink-0 mr-2" />
                                You have a school-issued email address
                            </li>
                            <li className="flex items-center text-sm">
                                <IconCheck className="text-muted shrink-0 mr-2" />
                                You're building something you can tell us about
                            </li>
                        </ul>
                    </div>
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
                                    To be eligible for the student program, you need to be on a paid plan.
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
                                <LemonButton type="primary" to={urls.projectRoot()}>
                                    Return to PostHog
                                </LemonButton>
                            </div>
                        ) : (
                            <Form
                                logic={studentProgramLogic}
                                formKey="studentProgram"
                                enableFormOnSubmit
                                className="space-y-3"
                            >
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

                                <LemonField name="school_name" label="School or university">
                                    <LemonInput placeholder="Your school or university" />
                                </LemonField>

                                <LemonField
                                    name="academic_email"
                                    label="Academic email"
                                    info="Use your school-issued email address. We use it to verify your enrollment."
                                >
                                    <LemonInput placeholder="you@university.edu" />
                                </LemonField>

                                <LemonField name="expected_graduation_date" label="Expected graduation date">
                                    <LemonCalendarSelectInput
                                        clearable={false}
                                        format="YYYY-MM-DD"
                                        buttonProps={{ className: 'bg-bg-light' }}
                                        placeholder=" "
                                        selectionPeriod="upcoming"
                                    />
                                </LemonField>

                                <LemonField name="project_description" label="What are you building?">
                                    <LemonTextArea
                                        placeholder="A sentence or two about your product, startup, research, or class project. Links welcome."
                                        minRows={2}
                                    />
                                </LemonField>

                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    className="mt-4"
                                    data-attr="student-program-submit"
                                >
                                    Submit application
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

export default StudentProgram
