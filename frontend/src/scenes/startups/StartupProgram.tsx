import { LemonButton, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
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
    const programName = isYC ? 'YC Program' : 'Startup Program'

    if (formSubmitted) {
        return (
            <div className="mx-auto max-w-160 mt-10 px-4">
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
            <div className="mx-auto max-w-160 mt-10 px-4">
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
            <div className="mx-auto max-w-160 mt-10 px-4">
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
        <div className="mx-auto max-w-160 mt-10 px-4">
            <h1 className="text-center mb-8">{`PostHog ${programName} Application`}</h1>

            <div className="mb-8">
                <h2 className="mb-2">Program Benefits</h2>
                <ul className="list-disc pl-6">
                    <li className="mb-2">$50,000 in PostHog credits (valid for 1 year)</li>
                    <li className="mb-2">Founder merch (stickers, t-shirts, and more)</li>
                    <li className="mb-2">$25,000 in DigitalOcean credit through their Hatch program</li>
                </ul>

                <h3 className="mt-4 mb-2">Eligibility Requirements</h3>
                <ul className="list-disc pl-6">
                    <li className="mb-2">Company must be less than 2 years old</li>
                    <li className="mb-2">Less than $5 million in funding</li>
                </ul>
            </div>

            <LemonDivider className="my-6" />

            <Form
                logic={startupProgramLogic}
                props={{ isYC }}
                formKey="startupProgram"
                enableFormOnSubmit
                className="space-y-4"
            >
                <div className="grid md:grid-cols-2 gap-4">
                    <LemonField name="first_name" label="First name">
                        <LemonInput placeholder="Jane" />
                    </LemonField>

                    <LemonField name="last_name" label="Last name">
                        <LemonInput placeholder="Doe" />
                    </LemonField>
                </div>

                <LemonField name="email" label="Email">
                    <LemonInput placeholder="your@email.com" />
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
                    className="mt-4"
                    fullWidth
                    center
                    data-attr="startup-program-submit"
                >
                    Submit Application
                </LemonButton>
            </Form>
        </div>
    )
}

export default StartupProgram
