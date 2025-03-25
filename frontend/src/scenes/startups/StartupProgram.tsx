import { IconArrowRight, IconCheck, IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { SpaceHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
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
    const { formSubmitted, isAlreadyOnStartupPlan, isUserOrganizationOwnerOrAdmin } = useValues(logic)
    const { billing } = useValues(billingLogic)
    const programName = isYC ? 'YC Program' : 'Startup Program'

    if (formSubmitted) {
        return (
            <div className="mx-auto max-w-200 mt-6 px-4">
                <LemonBanner type="success">
                    <h2 className="mb-2">Thank you for your application!</h2>
                    <p>
                        We'll review your application and get back to you as soon as possible. In the meantime, you can
                        continue using PostHog.
                    </p>
                    <LemonButton type="primary" to={urls.projectHomepage()} className="mt-2">
                        Return to PostHog
                    </LemonButton>
                </LemonBanner>
            </div>
        )
    }

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
        <div className="mx-auto max-w-[1200px] mt-6 px-4">
            <div className="flex flex-col items-center mb-8">
                <SpaceHog className="w-[200px] h-auto mb-3" />
                <h1 className="text-center text-3xl mb-3">
                    {isYC ? 'Welcome to PostHog for YC Companies' : 'PostHog for Startups'}
                </h1>
                <p className="text-center text-base text-muted max-w-160">
                    {isYC
                        ? 'Get started with PostHog, the all-in-one Product OS built for YC founders. Enjoy $50,000 in credits and exclusive benefits.'
                        : 'Get $50,000 in credits and exclusive benefits to help you build a better product with PostHog.'}
                </p>
            </div>

            <div className="grid md:grid-cols-2 gap-8 mb-8">
                <div className="bg-surface-secondary rounded-lg p-6">
                    <h2 className="text-xl mb-4">Program Benefits</h2>
                    <div className="space-y-3">
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">$50,000 in PostHog credits</h4>
                                <p className="text-muted text-sm">
                                    Valid for 1 year to use across all PostHog products
                                </p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">Founder merch</h4>
                                <p className="text-muted text-sm">
                                    Exclusive PostHog swag pack with stickers, t-shirts, and more
                                </p>
                            </div>
                        </div>
                        <div className="flex items-start">
                            <IconCheck className="text-success shrink-0 mt-1 mr-2" />
                            <div>
                                <h4 className="font-semibold">$25,000 in DigitalOcean credits</h4>
                                <p className="text-muted text-sm">Through their Hatch program for startups</p>
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
                            <h3 className="text-lg mb-3">Eligibility Requirements</h3>
                            <ul className="space-y-2">
                                <li className="flex items-center text-sm">
                                    <IconArrowRight className="text-muted shrink-0 mr-2" />
                                    Company must be less than 2 years old
                                </li>
                                <li className="flex items-center text-sm">
                                    <IconArrowRight className="text-muted shrink-0 mr-2" />
                                    Less than $5 million in funding
                                </li>
                            </ul>
                        </div>
                    )}
                </div>

                <div className="space-y-4">
                    {/* Step 1: Upgrade to a paid plan */}
                    <div className="bg-surface-secondary rounded-lg p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-xl m-0">Step 1: Upgrade to a paid plan</h2>
                        </div>
                        {billing?.has_active_subscription ? (
                            <div className="flex items-center gap-2 text-success">
                                <IconCheck className="shrink-0" />
                                <span>You're on a paid plan</span>
                            </div>
                        ) : (
                            <div className="flex flex-col items-start gap-2">
                                <p className="text-muted mb-2">
                                    To be eligible for the startup program, you need to be on a paid plan. Don't worry -
                                    you'll only pay for what you use and can set billing limits as low as $0 to control
                                    your spend.
                                </p>
                                <p className="text-muted mb-4 italic">
                                    P.S. You still keep the monthly free allowance for every product!
                                </p>
                                <LemonButton type="primary" to={urls.organizationBilling()}>
                                    Add billing details
                                </LemonButton>
                            </div>
                        )}
                    </div>

                    {/* Step 2: Submit application form */}
                    <div className="bg-surface-secondary rounded-lg p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-xl m-0">Step 2: Submit application</h2>
                            {formSubmitted && <IconCheckCircle className="text-success text-2xl" />}
                        </div>
                        <Form
                            logic={startupProgramLogic}
                            props={{ isYC }}
                            formKey="startupProgram"
                            enableFormOnSubmit
                            className="space-y-3"
                        >
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

                            <LemonField name="posthog_organization_name" label="PostHog organization name">
                                <LemonInput placeholder="Your PostHog organization" />
                            </LemonField>

                            <LemonField name="raised" label="How much in total funding have you raised (USD)">
                                <LemonSelect options={RAISED_OPTIONS} />
                            </LemonField>

                            <LemonField name="incorporation_date" label="The date that your company was incorporated">
                                <LemonCalendarSelectInput clearable={false} format="YYYY-MM-DD" />
                            </LemonField>

                            <LemonField name="is_building_with_llms" label="Are you building LLM-powered features?">
                                <LemonSelect
                                    options={[
                                        { label: 'Yes', value: 'true' },
                                        { label: 'No', value: 'false' },
                                    ]}
                                />
                            </LemonField>

                            {isYC && (
                                <LemonField name="yc_batch" label="Which YC batch are you?">
                                    <LemonSelect options={YC_BATCH_OPTIONS} />
                                </LemonField>
                            )}

                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                className="mt-3"
                                fullWidth
                                center
                                data-attr="startup-program-submit"
                            >
                                Submit Application
                            </LemonButton>

                            {/* This will display a form error if user is not on a paid plan. Kea forms requires a child element */}
                            <LemonField name="_form">
                                <span />
                            </LemonField>
                        </Form>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default StartupProgram
