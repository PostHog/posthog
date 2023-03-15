import { LemonButton, LemonCollapse, LemonDivider, LemonModal, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { urls, AdHocInsight } from '@posthog/apps-common'
import { useActions, useValues } from 'kea'
import { feedbackLogic } from './feedbackLogic'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import './Feedback.scss'
import { IconHelpOutline } from 'lib/lemon-ui/icons'
import { Query } from '~/queries/Query/Query'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'

const OPT_IN_SNIPPET = `posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`

const SEND_FEEDBACK_SNIPPET = `posthog.capture('Feedback Sent', {
    '$feedback': 'Can you make the logo bigger?'
})`

export function FeedbackInstructions(): JSX.Element {
    const { inAppFeedbackInstructions } = useValues(feedbackLogic)
    const { toggleInAppFeedbackInstructions } = useActions(feedbackLogic)
    return (
        <LemonModal
            title="How to send in-app feedback to Posthog"
            isOpen={inAppFeedbackInstructions}
            onClose={toggleInAppFeedbackInstructions}
        >
            <div className="w-160">
                <LemonCollapse
                    defaultActiveKey="1"
                    panels={[
                        {
                            key: '1',
                            header: 'Install the feedback app',
                            content: (
                                <div>
                                    <div>
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

function getFilters(eventName: string): Record<string, any> {
    return {
        insight: 'TRENDS',
        events: [{ id: eventName, name: eventName, type: 'events', order: 0 }],
        actions: [],
        display: 'ActionsLineGraph',
        interval: 'day',
        new_entity: [],
        properties: [],
        filter_test_accounts: false,
        date_from: '-30d',
    }
}

function InAppFeedback({
    config,
}: {
    config: {
        eventName: string
        feedbackProperty: string
    }
}): JSX.Element {
    const { eventName } = config
    const filters = getFilters(eventName)

    const { query } = useValues(feedbackLogic)
    const { setQuery } = useActions(feedbackLogic)

    const { toggleInAppFeedbackInstructions } = useActions(feedbackLogic)
    // TODO: add setQuery

    // TODO call the events endpoint to get the feedback events and allow adding new events

    return (
        <>
            <div className="flex w-full justify-between">
                <h3 className="text-lg">Feedback received in the last 30 days</h3>
                <LemonButton
                    onClick={() => {
                        toggleInAppFeedbackInstructions()
                    }}
                    sideIcon={<IconHelpOutline />}
                >
                    Show instructions
                </LemonButton>
            </div>
            <AdHocInsight filters={filters} style={{ height: 200 }} />
            <LemonDivider className="my-6" />
            <Query query={query} setQuery={setQuery} />
        </>
    )
}

function FeedbackWidgetTab({
    config,
}: {
    config: {
        eventName: string
        feedbackProperty: string
    }
}): JSX.Element {
    // const { eventName } = config
    const { eventsLoading } = useValues(feedbackLogic)

    return (
        <>
            {eventsLoading ? (
                <div>Loading...</div>
            ) : (
                <>
                    <InAppFeedback config={config} />
                </>
            )}
        </>
    )
}

export const Feedback = (): JSX.Element => {
    return (
        <div className="Feedback">
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Feedback
                        <LemonTag type="warning" className="uppercase">
                            Alpha
                        </LemonTag>
                    </div>
                }
            />
            <LemonTabs
                activeKey="in-app-feedback"
                onChange={function noRefCheck() {}}
                tabs={[
                    {
                        content: (
                            <FeedbackWidgetTab
                                config={{
                                    eventName: 'Feedback Sent',
                                    feedbackProperty: '$feedback',
                                }}
                            />
                        ),
                        key: 'in-app-feedback',
                        label: 'In-app feedback',
                    },
                    {
                        content: <div>Imagine some calculator here. 🔢</div>,
                        key: 'user-interview-scheduler',
                        label: 'User interview scheduler',
                    },
                ]}
            />
            <FeedbackInstructions />
        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    logic: feedbackLogic,
}
