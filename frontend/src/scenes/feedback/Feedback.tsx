import { LemonButton, LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { urls, Link, PersonHeader, AdHocInsight, TZLabel } from '@posthog/apps-common'
import { LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { feedbackLogic } from './feedbackLogic'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import './Feedback.scss'
import { IconClose, IconHelpOutline, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'

export function ExpandableSection({
    header,
    children,
    expanded,
    setExpanded,
}: {
    header: JSX.Element
    children: JSX.Element
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}): JSX.Element {
    return (
        <div className="rounded border p-4 my-4">
            <div
                className="flex cursor-pointer"
                onClick={() => {
                    setExpanded(!expanded)
                }}
            >
                <LemonButton
                    className="inline-flex items-center justify-center mr-2 mb-2"
                    status="stealth"
                    noPadding={true}
                    onClick={() => setExpanded(!expanded)}
                    icon={expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                    title={expanded ? 'Collapse' : 'Expand'}
                />
                <div className="inline-flex">{header}</div>
            </div>
            <div>{expanded && children}</div>
        </div>
    )
}

const OPT_IN_SNIPPET = `posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`

export function FeedbackInstructions(): JSX.Element {
    const { expandedSection } = useValues(feedbackLogic)
    const { setExpandedSection } = useActions(feedbackLogic)

    return (
        <div className="max-w-200">
            <ExpandableSection
                header={<h2 className="text-xl">Set up the feedback widget</h2>}
                expanded={expandedSection(0)}
                setExpanded={(expanded) => setExpandedSection(0, expanded)}
            >
                <div>
                    <p className="text-sm italic">
                        The feedback widget is the quickest way to collect feedback from your users.
                    </p>
                    <div>
                        <div>
                            <div className="text-lg">1. Turn on the feedback widget</div>
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
                            <div className="text-lg">2. Enable site apps</div>
                            <div className="ml-4 my-4">
                                <CodeSnippet language={Language.JavaScript} wrap>
                                    {OPT_IN_SNIPPET}
                                </CodeSnippet>
                            </div>
                        </div>
                        <div>
                            <div className="text-lg">3. Configure the feedback widget</div>
                            <div className="ml-4 my-4 text-base">
                                <p>Configure the feedback widget one of the following ways:</p>
                                <ul className="list-disc ml-4">
                                    <li>
                                        <strong>Floating feedback button:</strong> Select show feedback button on the
                                        page to have a floating feedback button on your website.
                                    </li>
                                    <li>
                                        <strong>Custom button:</strong> Add a button with a corresponding data attribute
                                        e.g. data-attr='posthog-feedback-button'. When clicked this will open the
                                        feedback widget
                                    </li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </ExpandableSection>
            <div>
                <div className="flex justify-center items-center">
                    <LemonDivider dashed className="flex-1" />
                    <h4 className="text-lg mx-4 text-muted mt-auto mb-auto">OR</h4>
                    <LemonDivider dashed className="flex-1" />
                </div>
            </div>
            <ExpandableSection
                header={<h2 className="text-xl">Create a custom feedback form</h2>}
                expanded={expandedSection(1)}
                setExpanded={(expanded) => setExpandedSection(1, expanded)}
            >
                <div>
                    <p className="text-sm italic">
                        Create a custom form styled to your app and then send the feedback to PostHog.
                    </p>
                    <div>
                        <div>
                            <div className="text-lg">1. Create the form</div>
                        </div>
                        <div>
                            <div className="text-lg">2. Send the feedback to PostHog</div>
                            <div className="ml-4 my-4">
                                <CodeSnippet language={Language.JavaScript} wrap>
                                    {`posthog.capture('Feedback Sent', { '$feedback': 'Can you make the logo bigger?' })`}
                                </CodeSnippet>
                            </div>
                        </div>
                    </div>
                </div>
            </ExpandableSection>
        </div>
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

    const { events } = useValues(feedbackLogic)

    // TODO call the events endpoint to get the feedback events and allow adding new events

    return (
        <>
            <h2>Feedback received in the last 30 days</h2>
            <AdHocInsight filters={filters} style={{ height: 200 }} />
            <LemonTable
                dataSource={events}
                columns={[
                    {
                        key: 'feedback',
                        title: 'Feedback',
                        render: (_, event) => {
                            return <div>{event.properties[config.feedbackProperty || '$feedback']}</div>
                        },
                    },
                    {
                        key: 'distinct_id',
                        title: 'Author',
                        render: (_, event) => {
                            console.log({ event })
                            return event.person ? (
                                <Link to={urls.person(event.person.distinct_ids[0])}>
                                    <PersonHeader noLink withIcon person={event.person} />
                                </Link>
                            ) : (
                                'Unknown user'
                            )
                        },
                    },
                    {
                        key: 'timestamp',
                        title: 'Sent',
                        render: (_, event) => <TZLabel time={event.timestamp} showSeconds />,
                    },
                ]}
            />
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
    const { events, eventsLoading } = useValues(feedbackLogic)

    const { inAppFeedbackInstructions } = useValues(feedbackLogic)
    const { toggleInAppFeedbackInstructions } = useActions(feedbackLogic)

    return (
        <>
            <div className="flex justify-end">
                {events && events.length > 0 && (
                    <LemonButton
                        onClick={() => {
                            toggleInAppFeedbackInstructions()
                        }}
                        sideIcon={!inAppFeedbackInstructions ? <IconHelpOutline /> : <IconClose />}
                    >
                        {!inAppFeedbackInstructions ? 'Show' : 'Hide'} instructions
                    </LemonButton>
                )}
            </div>
            {eventsLoading ? (
                <div>Loading...</div>
            ) : events && events.length === 0 ? (
                <>
                    <div className="mb-8">
                        <h3 className="text-2xl">No feedback received in the last 14 days.</h3>
                        <p className="text-sm italic">Starting sending feedback to use this feature. </p>
                    </div>
                    <FeedbackInstructions />
                </>
            ) : inAppFeedbackInstructions ? (
                <FeedbackInstructions />
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
                caption={<p>Hear what your users have to say about your product.</p>}
            />
            <FeedbackWidgetTab
                config={{
                    eventName: 'Feedback Sent',
                    feedbackProperty: '$feedback',
                }}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    logic: feedbackLogic,
}
