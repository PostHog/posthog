import { useValues } from 'kea'
import { Map } from 'lib/components/Map'
import React from 'react'
import { personsLogic } from './personsLogic'
import { Marker } from 'maplibre-gl'
import { EventsTable } from 'scenes/events'
import { urls } from 'scenes/urls'
import { LemonRow } from '@posthog/lemon-ui'
import { IconPlace, IconSchedule } from 'lib/components/icons'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'

export function PersonFeed(): JSX.Element {
    const { person, personCoordinates, personPlace, personTimezone, urlId } = useValues(personsLogic)

    if (!person) {
        throw new Error("Can't render PersonsFeed without person.")
    }

    return (
        <div className="flex w-full gap-2">
            <div className="flex-1 min-w-0">
                {' '}
                <EventsTable
                    pageKey={person.distinct_ids.join('__')} // force refresh if distinct_ids change
                    fixedFilters={{ person_id: person.id }}
                    showPersonColumn={false}
                    sceneUrl={urls.person(urlId || person.distinct_ids[0] || String(person.id))}
                />
            </div>
            <div className="border rounded shrink-0 h-fit overflow-hidden" style={{ width: '18rem' }}>
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
                    {person.properties && Object.keys(person.properties).length > 0 && (
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
            </div>
        </div>
    )
}
