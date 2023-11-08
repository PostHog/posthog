import { LemonButton, LemonCollapse, LemonDivider, LemonModal, Link } from '@posthog/lemon-ui'

import { urls } from '@posthog/apps-common'
import { useActions, useValues } from 'kea'
import { inAppFeedbackLogic } from './inAppFeedbackLogic'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import './Feedback.scss'
import { IconHelpOutline } from 'lib/lemon-ui/icons'
import { Query } from '~/queries/Query/Query'

const OPT_IN_SNIPPET = `posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`

const SEND_FEEDBACK_SNIPPET = `posthog.capture('Feedback Sent', {
    '$feedback': 'Can you make the logo bigger?'
})`

export function FeedbackInstructions(): JSX.Element {
    const { inAppFeedbackInstructions } = useValues(inAppFeedbackLogic)
    const { toggleInAppFeedbackInstructions } = useActions(inAppFeedbackLogic)
    return (
        <LemonModal
            title="How to send in-app feedback to PostHog"
            isOpen={inAppFeedbackInstructions}
            onClose={toggleInAppFeedbackInstructions}
            width={640}
        >
            <div>
                <LemonCollapse
                    defaultActiveKey="1"
                    panels={[
                        {
                            key: '1',
                            header: 'Install the feedback app',
                            content: (
                                <div>
                                    <div>
                                        <p>
                                            PostHog's in-app widget is quickest way to get started managing customer
                                            feedback.
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
                            header: 'Create a custom feedback form',
                            content: (
                                <div>
                                    <div>
                                        <p>Build a custom feedback form to connect feedback styled to your brand.</p>
                                        <div>
                                            <div>1. Create a custom form in your webapp app or mobile app</div>
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

export function InAppFeedbackHeaderButtons(): JSX.Element {
    const { toggleInAppFeedbackInstructions } = useActions(inAppFeedbackLogic)
    return (
        <>
            <LemonButton
                onClick={() => {
                    toggleInAppFeedbackInstructions()
                }}
                sideIcon={<IconHelpOutline />}
            >
                Feedback instructions
            </LemonButton>
            <FeedbackInstructions />
        </>
    )
}

export function InAppFeedback(): JSX.Element {
    const { dataTableQuery, trendQuery } = useValues(inAppFeedbackLogic)
    const { setDataTableQuery } = useActions(inAppFeedbackLogic)

    const { toggleInAppFeedbackInstructions } = useActions(inAppFeedbackLogic)

    const { events, eventsLoading } = useValues(inAppFeedbackLogic)

    // TODO call the events endpoint to get the feedback events and allow adding new events

    return (
        <>
            {!eventsLoading && events.length === 0 && (
                <div>
                    No events found.{' '}
                    <Link
                        onClick={() => {
                            toggleInAppFeedbackInstructions()
                        }}
                    >
                        Send feedback
                    </Link>{' '}
                    to use this feature.
                </div>
            )}
            <Query query={trendQuery} readOnly />
            <LemonDivider className="my-6" />
            <Query query={dataTableQuery} setQuery={setDataTableQuery} />
        </>
    )
}
