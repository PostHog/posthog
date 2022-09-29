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
import { Session, SessionsList } from './SessionsList'

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

    const SESSIONS: Session[] = [
        {
            id: 'session1',
            eventsWithActionMatches: [
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
                        timestamp: '2021-10-01T00:00:00.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actionIds: [1],
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
                        timestamp: '2021-10-01T00:01:01.000Z',
                        elements: [],
                        elements_hash: '',
                    },
                    actionIds: [1],
                },
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
                    actionIds: [1],
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

    return (
        <div className="flex-1">
            <SessionsList sessions={SESSIONS} />
        </div>
    )
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
