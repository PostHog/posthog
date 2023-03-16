import { LemonButton, LemonCollapse, LemonModal } from '@posthog/lemon-ui'

import { urls } from '@posthog/apps-common'
import { useActions, useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import './Feedback.scss'
import { IconHelpOutline } from 'lib/lemon-ui/icons'
import { userInterviewSchedulerLogic } from './userInterviewSchedulerLogic'
import { OverViewTab } from 'scenes/feature-flags/FeatureFlags'

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
        >
            <div className="w-160">
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
                                                1. Create a custom popup based on{' '}
                                                <a href="https://github.com/PostHog/user-interview-app/blob/main/site.ts">
                                                    PostHog's open-source popup code
                                                </a>
                                            </div>
                                            <div className="ml-4 my-4">
                                                <ul className="list-disc ml-4">
                                                    <li>
                                                        <strong>Show the popup</strong> The popup should show when a
                                                        flag with the prefix <code>interview-</code> is enabled.
                                                    </li>
                                                    <li>
                                                        <strong>Hide the popup</strong> Hide the popup when the user
                                                        clicks <code>Close</code> or <code>Book</code>. Then use local
                                                        storage to disable it from showing again and set the user
                                                        properties to prevent is showing across devices. (See the code
                                                        for an example)
                                                    </li>
                                                    <li>
                                                        <strong>Send events</strong> Send events to PostHog when the
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

export function UserInterviewScheduler(): JSX.Element {
    const { toggleSchedulerInstructions } = useActions(userInterviewSchedulerLogic)

    return (
        <>
            <div className="flex w-full justify-between">
                <div>
                    <h3 className="text-lg">User Interview Scheduler</h3>
                </div>
                <div className="flex gap-2">
                    <LemonButton
                        onClick={() => {
                            toggleSchedulerInstructions()
                        }}
                        sideIcon={<IconHelpOutline />}
                    >
                        Set up instructions
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            // TODO create the interview invitation
                        }}
                    >
                        Create interview invitation
                    </LemonButton>
                </div>
            </div>
            <div className="my-4" />
            <OverViewTab flagPrefix="interview-" searchPlaceholder="Search interview invitations" />
            <SchedulerInstructions />
        </>
    )
}
