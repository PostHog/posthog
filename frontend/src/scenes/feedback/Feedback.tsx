import { LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import React, { useState, useEffect } from 'react'
import { api, urls, Link, PersonHeader, AdHocInsight, TZLabel } from '@posthog/apps-common'
import { LemonTable } from '@posthog/lemon-ui'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useActions, useValues } from 'kea'
import { feedbackLogic } from './feedbackLogic'
import { EventType } from '~/types'

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

function FeedbackWidget({
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

    return (
        <>
            <h2>Feedback received in the last 14 days</h2>
            {eventsLoading ? (
                <div>Loading...</div>
            ) : events.length === 0 ? (
                <div>No feedback has been submitted</div>
            ) : (
                <>
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
        <div className="web-performance">
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Feedback
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                caption={<p>Hear what your users have to say about your product</p>}
            />
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setTab(key)}
                tabs={[
                    {
                        content: (
                            <FeedbackWidget
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
                        content: <div>User interview scheduler</div>,
                        key: 'user-interview-scheduler',
                        label: 'Interview scheduler',
                    },
                ]}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Feedback,
    // logic: webPerformanceLogic,
    paramsToProps: () => ({ sceneUrl: urls.feedback() }),
}
