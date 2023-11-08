import { LemonButton, LemonCollapse, LemonInput, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'

import { urls } from '@posthog/apps-common'
import { useActions, useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { IconHelpOutline } from 'lib/lemon-ui/icons'
import { FLAG_PREFIX, userInterviewSchedulerLogic } from './userInterviewSchedulerLogic'
import { OverViewTab } from 'scenes/feature-flags/FeatureFlags'
import { Form } from 'kea-forms'

import './UserInterviewScheduler.scss'
import { Field } from 'lib/forms/Field'

const OPT_IN_SNIPPET = `posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`

export function SchedulerInstructions(): JSX.Element {
    const { schedulerInstructions } = useValues(userInterviewSchedulerLogic)
    const { toggleSchedulerInstructions } = useActions(userInterviewSchedulerLogic)
    return (
        <LemonModal
            title="How to set up the interview scheduler popup"
            isOpen={schedulerInstructions}
            onClose={toggleSchedulerInstructions}
            width={640}
        >
            <div>
                <p>
                    The interview scheduler is powered by JSON feature flags. It requires setting up the interview
                    scheduler app or building a custom popup:
                </p>
                <LemonCollapse
                    defaultActiveKey="1"
                    panels={[
                        {
                            key: '1',
                            header: 'Install the interview scheduler app',
                            content: (
                                <div>
                                    <div>
                                        <p>
                                            PostHog's user interview scheduler app is the quickest way to start inviting
                                            customers to interview. Here's what it looks like:
                                        </p>
                                        <div className="flex justify-center">
                                            <img
                                                src="https://posthog.com/static/user-interview-app-44f939731dce197547b675bb92942e7e.png"
                                                className="w-80 m-auto"
                                            />
                                        </div>
                                        <div className="mt-4">1. Turn on the user interview scheduler app</div>
                                        <div className="ml-4 my-4">
                                            <LemonButton
                                                onClick={() => {
                                                    window.open(urls.projectAppSearch('User interview'), '_blank')
                                                }}
                                                type="primary"
                                            >
                                                User interview scheduler app
                                            </LemonButton>
                                        </div>
                                    </div>
                                    <div>
                                        <div>2. Enable site apps</div>
                                        <div className="ml-4 my-4">
                                            <CodeSnippet language={Language.JavaScript} wrap>
                                                {OPT_IN_SNIPPET}
                                            </CodeSnippet>
                                        </div>
                                    </div>
                                    <div>
                                        <div>3. Configure the User interview scheduler app:</div>
                                        <div className="ml-4 my-4">
                                            <ul className="list-disc ml-4">
                                                <li>
                                                    <strong>Domains:</strong> Add the domains where you want it to show
                                                </li>
                                                <li>
                                                    <strong>Invitation Title (default):</strong> Set a default title for
                                                    the popup
                                                </li>
                                                <li>
                                                    <strong>Invitation Body (default):</strong> Set a default body for
                                                    the popup, you can include images and links
                                                </li>
                                            </ul>
                                        </div>
                                    </div>
                                </div>
                            ),
                        },
                        {
                            key: '2',
                            header: 'Create a custom user interview scheduler',
                            content: (
                                <div>
                                    <div>
                                        <p>Build a custom user interview scheduler to match your brand.</p>
                                        <div>
                                            <div>
                                                1. Create a custom popup in your webapp or mobile app based on{' '}
                                                <Link to="https://github.com/PostHog/user-interview-app/blob/main/site.ts">
                                                    PostHog's open-source popup code
                                                </Link>
                                            </div>
                                            <div className="ml-4 my-4">
                                                <ul className="list-disc ml-4">
                                                    <li>
                                                        <strong>Show the popup:</strong> The popup should show when a
                                                        flag with the prefix <code>{FLAG_PREFIX}</code> is enabled.
                                                    </li>
                                                    <li>
                                                        <strong>Hide the popup:</strong> Hide the popup when the user
                                                        clicks <code>Close</code> or <code>Book</code>. Then use local
                                                        storage to disable it from showing again and set the user
                                                        properties to prevent is showing across devices. (See the code
                                                        for an example)
                                                    </li>
                                                    <li>
                                                        <strong>Send events:</strong> Send events to PostHog when the
                                                        user clicks the buttons. (See the code for the events)
                                                    </li>
                                                </ul>
                                            </div>
                                            <div>
                                                2. Create a user interview flag. The flag should have the prefix{' '}
                                                <code>interview-</code> and be enabled for the users you want to show it
                                                to. It should be disabled for the users with the property indicating
                                                they've already seen it. (See the code for an example)
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}

export function CreateInterviewFlag(): JSX.Element {
    const { interviewFlagModal, isInterviewFlagSubmitting } = useValues(userInterviewSchedulerLogic)

    const { toggleInterviewFlagModal } = useActions(userInterviewSchedulerLogic)

    return (
        <LemonModal
            title="Create a user interview flag"
            isOpen={interviewFlagModal}
            onClose={toggleInterviewFlagModal}
            width={600}
        >
            <Form logic={userInterviewSchedulerLogic} formKey="interviewFlag" enableFormOnSubmit className="space-y-2">
                <Field name="key" label="Key">
                    {({ value, onChange }) => <LemonInput value={value} onChange={onChange} />}
                </Field>
                <Field name="title" label="Invitation Title">
                    <LemonInput />
                </Field>
                <Field name="body" label="Invitation Body">
                    <LemonInput />
                </Field>
                <Field name="bookingLink" label="Booking Link">
                    <LemonInput />
                </Field>
                <Field name="description" label="What is the purpose of the interview? (Internal only)">
                    <LemonTextArea placeholder="What are these interviews for?" />
                </Field>
                <p>
                    Use the rollout conditions on the feature flag to set who the interview invitation is shown to. By
                    default, it is shown to no-one.
                </p>

                <div className="flex justify-end my-4">
                    <LemonButton loading={isInterviewFlagSubmitting} htmlType="submit" type="primary">
                        Create
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}

export function UserInterviewSchedulerHeaderButtons(): JSX.Element {
    const { toggleInterviewFlagModal, toggleSchedulerInstructions } = useActions(userInterviewSchedulerLogic)
    return (
        <>
            <div className="flex gap-2">
                <LemonButton
                    onClick={() => {
                        toggleSchedulerInstructions()
                    }}
                    sideIcon={<IconHelpOutline />}
                >
                    Scheduler instructions
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={() => {
                        toggleInterviewFlagModal()
                    }}
                >
                    Create interview invitation
                </LemonButton>
            </div>
            <SchedulerInstructions />
            <CreateInterviewFlag />
        </>
    )
}

export function UserInterviewScheduler(): JSX.Element {
    return (
        <div>
            <div className="my-4" />
            <OverViewTab
                flagPrefix={FLAG_PREFIX}
                searchPlaceholder="Search interview invitations"
                nouns={['invitation flag', 'invitation flags']}
            />
        </div>
    )
}
