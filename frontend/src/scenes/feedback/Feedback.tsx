import { LemonButton, LemonDivider, LemonInput, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { useState, useEffect } from 'react'
import { api, urls, Link, PersonHeader, AdHocInsight, TZLabel } from '@posthog/apps-common'
import { LemonTable } from '@posthog/lemon-ui'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useActions, useValues } from 'kea'
import { feedbackLogic } from './feedbackLogic'
import { EventType } from '~/types'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Field, Form } from 'kea-forms'

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

function useEvents(eventName: string): { events: EventType[]; eventsLoading: boolean } {
    const [events, setEvents] = useState<EventType[]>([])
    const [eventsLoading, setEventsLoading] = useState(true)
    useEffect(() => {
        const fetchEvents = async (): Promise<void> => {
            const response = await api.events.list({
                properties: [],
                event: eventName,
                orderBy: ['-timestamp'],
            })
            // TODO: improve typing
            setEvents(response.results as unknown as EventType[])
            setEventsLoading(false)
        }
        fetchEvents()
    }, [])
    return { events, eventsLoading }
}

function useFilters(eventName: string): Record<string, any> {
    return {
        insight: 'TRENDS',
        events: [{ id: eventName, name: eventName, type: 'events', order: 0 }],
        actions: [],
        display: 'ActionsLineGraph',
        interval: 'day',
        new_entity: [],
        properties: [],
        filter_test_accounts: false,
        date_from: '-14d',
    }
}

export function FeedbackInstructions(): JSX.Element {
    // what this does
    // instructions to install the feedback widget
    // instructions to send feedback directly
    // potentially config the eventName and feedbackProperty
    const formKey = 'newFeedbackEvent'
    const eventName = 'Feedback Sent'
    const feedbackProperties = ['$feedback']

    const { expandedSection } = useValues(feedbackLogic)
    const { setExpandedSection } = useActions(feedbackLogic)

    // TODO: Hook up the table and form to the API

    return (
        <div className="max-w-200">
            <ExpandableSection
                header={<h2 className="text-2xl">Set up the feedback widget</h2>}
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
                                    {`posthog.init('YOUR_PROJECT_API_KEY', {
    api_host: 'YOUR API HOST',
    opt_in_site_apps: true // <--- Add this line
})`}
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
                header={<h2 className="text-2xl">Create a custom feedback form</h2>}
                expanded={expandedSection(1)}
                setExpanded={(expanded) => setExpandedSection(1, expanded)}
            >
                <div>
                    <p className="text-sm italic">
                        Or create a custom form styled to your app and then send the feedback to PostHog.
                    </p>
                    <div>
                        <div>
                            <div className="text-lg">1. Create the form and send the feedback to PostHog</div>
                            <div className="ml-4 my-4">
                                <CodeSnippet language={Language.JavaScript} wrap>
                                    {`posthog.capture('Feedback Sent', { '$feedback': 'Can you make the logo bigger?' })`}
                                </CodeSnippet>
                            </div>
                        </div>
                        <div>
                            <div className="text-lg">2. Add your feedback properties</div>
                            <div className="ml-4 max-w-200 my-4 FeedbackEventsTable">
                                {/* Lemon table containing event name and event properties */}
                                <LemonTable
                                    dataSource={[
                                        {
                                            event: eventName,
                                            properties: feedbackProperties,
                                        },
                                    ]}
                                    columns={[
                                        {
                                            key: 'event',
                                            title: 'Feedback Event',
                                            render: (_, event) => {
                                                return <div>{event.event}</div>
                                            },
                                        },
                                        {
                                            key: 'properties',
                                            title: 'Feedback Properties',
                                            render: (_, event) => {
                                                return (
                                                    <div>
                                                        {event.properties.map((property: string, index: number) => (
                                                            <div key={index}>{property}</div>
                                                        ))}
                                                    </div>
                                                )
                                            },
                                        },
                                    ]}
                                />
                                <Form logic={feedbackLogic} formKey={formKey} className="my-4">
                                    <div className="flex gap-4">
                                        <div className="flex-1">
                                            <Field name="name">
                                                <LemonInput placeholder="Feedback Sent" />
                                            </Field>
                                        </div>
                                        <div className="flex-1">
                                            <div className="flex gap-4">
                                                <div className="flex-1">
                                                    <Field name="properties">
                                                        <LemonInput placeholder="$feedback,$feedback2" />
                                                    </Field>
                                                </div>
                                                <div>
                                                    <LemonButton
                                                        type="primary"
                                                        onClick={() => {
                                                            feedbackLogic.actions.addFeedbackProperty()
                                                        }}
                                                    >
                                                        Add
                                                    </LemonButton>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </Form>
                            </div>
                        </div>
                    </div>
                </div>
            </ExpandableSection>
        </div>
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
    const eventName = config.eventName || 'Feedback Sent'
    const { events, eventsLoading } = useEvents(eventName)
    const filters = useFilters(eventName)
    const { inAppFeedbackInstructions } = useValues(feedbackLogic)
    const { toggleInAppFeedbackInstructions } = useActions(feedbackLogic)

    return (
        <>
            <div className="flex justify-end float-right">
                {events.length > 0 && (
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
            ) : events.length === 0 ? (
                <>
                    <div className="mb-8">
                        <h3 className="text-2xl">No feedback received in the last 14 days.</h3>
                        <p className="text-sm italic">Starting sending feedback to use this feature. </p>
                    </div>
                    <FeedbackInstructions />
                </>
            ) : (
                <>
                    <h2>Feedback received in the last 14 days</h2>
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
            )}
        </>
    )
}

export const Feedback = (): JSX.Element => {
    const { activeTab } = useValues(feedbackLogic)
    const { setTab } = useActions(feedbackLogic)

    return (
        <div className="Feedback">
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Feedback
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                caption={<p>Hear what your users have to say about your product.</p>}
            />
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setTab(key)}
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
                        tooltip: 'Qualitative feedback sent from your app',
                    },
                    {
                        content: <div>User interview scheduler</div>,
                        key: 'user-interview-scheduler',
                        label: 'Interview scheduler',
                        tooltip: 'Schedule user interviews with your users',
                    },
                ]}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    logic: feedbackLogic,
}
