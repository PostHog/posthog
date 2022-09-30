import { useValues } from 'kea'
import { Map } from 'lib/components/Map'
import React from 'react'
import { personsLogic } from './personsLogic'
import { Marker } from 'maplibre-gl'
import { LemonRow } from '@posthog/lemon-ui'
import { IconPlace, IconSchedule } from 'lib/components/icons'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { Session, PersonFeedList } from './SessionsList'
import { EventWithActionMatches } from '~/types'

export function PersonFeed(): JSX.Element {
    return (
        <div className="flex w-full gap-2">
            <PersonSessions />
            <PersonSidebar />
        </div>
    )
}

export function PersonSessions(): JSX.Element {
    const { person } = useValues(personsLogic)

    if (!person) {
        throw new Error("Can't render PersonSessions without person.")
    }

    const FEED_ENTRIES: (Session | EventWithActionMatches[])[] = [
        {
            id: 'session3',
            eventsWithActionMatches: [
                {
                    event: {
                        id: 'event4',
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $browser: 'Chrome',
                            $os: 'Mac OS',
                            $screen_height: 1080,
                            $screen_width: 1920,
                            $lib: 'web',
                        },
                        timestamp: '2021-10-01T03:09:35.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actions: [],
                },
                {
                    event: {
                        id: 'event5',
                        event: '$autocapture',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $browser: 'Chrome',
                            $os: 'Mac OS',
                            $screen_height: 1080,
                            $screen_width: 1920,
                            $lib: 'web',
                        },
                        timestamp: '2021-10-01T03:05:00.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actions: [
                        {
                            id: 2,
                            name: 'action2',
                            steps: [],
                            created_at: '2021-10-01T00:00:00.000Z',
                            deleted: false,
                            is_calculating: false,
                            last_calculated_at: '2021-10-01T00:00:00.000Z',
                            post_to_slack: false,
                            slack_message_format: '',
                            created_by: null,
                        },
                    ],
                },
                {
                    event: {
                        id: 'event6',
                        event: '$autocapture',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $browser: 'Chrome',
                            $os: 'Mac OS',
                            $screen_height: 1080,
                            $screen_width: 1920,
                            $lib: 'web',
                        },
                        timestamp: '2021-10-01T03:04:00.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actions: [
                        {
                            id: 1,
                            name: 'action1',
                            steps: [],
                            created_at: '2021-10-01T00:00:00.000Z',
                            deleted: false,
                            is_calculating: false,
                            last_calculated_at: '2021-10-01T00:00:00.000Z',
                            post_to_slack: false,
                            slack_message_format: '',
                            created_by: null,
                        },
                    ],
                },
                {
                    event: {
                        id: 'event7',
                        event: '$pageleave',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $browser: 'Chrome',
                            $os: 'Mac OS',
                            $screen_height: 1080,
                            $screen_width: 1920,
                            $lib: 'web',
                        },
                        timestamp: '2021-10-01T03:03:19.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actions: [],
                },
            ],
            recordings: [],
        },
        [
            {
                event: {
                    id: 'event99',
                    event: 'sent bill',
                    properties: {
                        amount: '10.99',
                        currency: 'USD',
                    },
                    timestamp: '2021-10-01T01:09:11.980Z',
                    elements: [],
                    elements_hash: '',
                },
                actions: [
                    {
                        id: 1,
                        name: 'action1',
                        steps: [],
                        created_at: '2021-10-01T00:00:00.000Z',
                        deleted: false,
                        is_calculating: false,
                        last_calculated_at: '2021-10-01T00:00:00.000Z',
                        post_to_slack: false,
                        slack_message_format: '',
                        created_by: null,
                    },
                ],
            },
            {
                event: {
                    id: 'event99',
                    event: 'charged card',
                    properties: {
                        amount: '10.99',
                        currency: 'USD',
                    },
                    timestamp: '2021-10-01T01:09:11.000Z',
                    elements: [],
                    elements_hash: '',
                },
                actions: [
                    {
                        id: 1,
                        name: 'action1',
                        steps: [],
                        created_at: '2021-10-01T00:00:00.000Z',
                        deleted: false,
                        is_calculating: false,
                        last_calculated_at: '2021-10-01T00:00:00.000Z',
                        post_to_slack: false,
                        slack_message_format: '',
                        created_by: null,
                    },
                ],
            },
        ],
        {
            id: 'session1',
            eventsWithActionMatches: [
                {
                    event: {
                        id: 'event3',
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $browser: 'Chrome',
                            $os: 'Mac OS',
                            $screen_height: 1080,
                            $screen_width: 1920,
                            $lib: 'web',
                        },
                        timestamp: '2021-10-01T00:03:19.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actions: [],
                },
                {
                    event: {
                        id: 'event1',
                        event: 'event1',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $browser: 'Chrome',
                            $os: 'Mac OS',
                            $screen_height: 1080,
                            $screen_width: 1920,
                            $lib: 'web',
                        },
                        timestamp: '2021-10-01T00:01:01.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actions: [],
                },
                {
                    event: {
                        id: 'event2',
                        event: '$autocapture',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $browser: 'Chrome',
                            $os: 'Mac OS',
                            $screen_height: 1080,
                            $screen_width: 1920,
                            $lib: 'web',
                        },
                        timestamp: '2021-10-01T00:00:00.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actions: [
                        {
                            id: 1,
                            name: 'action1',
                            steps: [],
                            created_at: '2021-10-01T00:00:00.000Z',
                            deleted: false,
                            is_calculating: false,
                            last_calculated_at: '2021-10-01T00:00:00.000Z',
                            post_to_slack: false,
                            slack_message_format: '',
                            created_by: null,
                        },
                    ],
                },
            ],
            recordings: [
                {
                    id: 'recording1',
                    viewed: true,
                    recording_duration: 196,
                    start_time: '2021-10-01T00:00:03.000Z',
                    end_time: '2021-10-01T00:03:19.000Z',
                },
            ],
        },
    ]

    return <PersonFeedList entries={FEED_ENTRIES} />
}

export function PersonSidebar(): JSX.Element | null {
    const { person, personCoordinates, personPlace, personTimezone } = useValues(personsLogic)

    if (!person) {
        throw new Error("Can't render PersonSessions without person.")
    }

    const personPropertiesNonEmpty: boolean = person.properties && Object.keys(person.properties).length > 0

    const personMetadataAvailable = !!(personCoordinates || personPlace || personTimezone || personPropertiesNonEmpty)

    return (
        <div className="border rounded shrink-0 h-fit overflow-hidden" style={{ width: '18rem' }}>
            {personMetadataAvailable ? (
                <>
                    {personCoordinates && (
                        <Map
                            center={personCoordinates}
                            markers={[new Marker({ color: 'var(--primary)' }).setLngLat(personCoordinates)]}
                            style={{ height: '14rem', borderBottomWidth: 1 }}
                        />
                    )}
                    <div className="w-full px-2 my-2">
                        <div className="w-full my-2">
                            {personPlace && (
                                <LemonRow icon={<IconPlace />} fullWidth>
                                    {personPlace}
                                </LemonRow>
                            )}
                            {personTimezone && (
                                <LemonRow icon={<IconSchedule />} fullWidth>
                                    {personTimezone}
                                </LemonRow>
                            )}
                        </div>
                        {personPropertiesNonEmpty && (
                            <div className="w-full p-2 pt-4 my-2 space-y-3 border-t">
                                <h3 className="text-lg font-bold">All properties</h3>
                                {Object.entries(person.properties).map(([key, value]) => (
                                    <div key={key}>
                                        <LemonLabel>
                                            <PropertyKeyInfo value={key} />
                                        </LemonLabel>
                                        <PropertiesTable properties={value} rootKey={key} />
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </>
            ) : (
                <div className="p-2 italic">There's no metadata for this person.</div>
            )}
        </div>
    )
}
