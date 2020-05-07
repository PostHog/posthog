import React, { useState } from 'react'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import moment from 'moment'
import { EventElements } from 'scenes/events/EventElements'

export function EventDetails({ event }) {
    const [selected, setSelected] = useState('properties')

    return (
        <div className="row">
            <div className="col-2">
                <div className="nav flex-column nav-pills" id="v-pills-tab" role="tablist" aria-orientation="vertical">
                    <a
                        className={'cursor-pointer nav-link ' + (selected === 'properties' && 'active')}
                        onClick={() => setSelected('properties')}
                    >
                        Properties
                    </a>
                    {event.elements.length > 0 && (
                        <a
                            className={'cursor-pointer nav-link ' + (selected === 'elements' && 'active')}
                            onClick={() => setSelected('elements')}
                        >
                            Elements
                        </a>
                    )}
                </div>
            </div>
            <div className="col-10">
                {selected === 'properties' ? (
                    <div className="d-flex flex-wrap flex-column" style={{ maxWidth: '100%', overflow: 'scroll' }}>
                        <PropertiesTable
                            properties={{
                                Timestamp: moment(event.timestamp).toISOString(),
                                ...event.properties,
                            }}
                        />
                    </div>
                ) : (
                    <EventElements event={event} />
                )}
            </div>
        </div>
    )
}
