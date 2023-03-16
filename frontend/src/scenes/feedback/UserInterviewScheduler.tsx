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

const SEND_FEEDBACK_SNIPPET = `posthog.capture('Feedback Sent', {
    '$feedback': 'Can you make the logo bigger?'
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
                                            customers to interview.
                                        </p>
                                        <div>1. Turn on the feedback widget</div>
                                        <div className="ml-4 my-4">
                                            <LemonButton
                                                onClick={() => {
                                                    window.open(urls.projectAppSearch('Feedback Widget'), '_blank')
                                                }}
                                                type="primary"
                                            >
                                                Feedback widget
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
                                        <div>3. Configure the feedback widget one of the following ways:</div>
                                        <div className="ml-4 my-4">
                                            <ul className="list-disc ml-4">
                                                <li>
                                                    <strong>Floating feedback button:</strong> Select show feedback
                                                    button on the page to have a floating feedback button on your
                                                    website.
                                                </li>
                                                <li>
                                                    <strong>Custom button:</strong> Add a button with a corresponding
                                                    data attribute e.g. data-attr='posthog-feedback-button'. When
                                                    clicked this will open the feedback widget
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
                                            <div>1. Create a custom form styled to your app</div>
                                        </div>
                                        <div>
                                            <div>2. Send the feedback to PostHog</div>
                                            <div className="ml-4 my-4">
                                                <CodeSnippet language={Language.JavaScript} wrap>
                                                    {SEND_FEEDBACK_SNIPPET}
                                                </CodeSnippet>
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
                <h3 className="text-lg">User Interview Scheduler</h3>
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
            <OverViewTab flagPrefix="interview-" />
            <SchedulerInstructions />
        </>
    )
}
