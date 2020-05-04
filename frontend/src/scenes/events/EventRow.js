import React from 'react'
import { Link } from 'react-router-dom'
import moment from 'moment'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'

const eventNameMap = event => {
    if (event.properties.$event_type === 'click') return 'clicked '
    if (event.properties.$event_type === 'change') return 'typed something into '
    if (event.properties.$event_type === 'submit') return 'submitted '
    return event.event
}

export function EventRow({ event, highlightEvents, selectedEvent, properties, setSelectedEvent, filtersEnabled }) {
    let params = ['$current_url', '$lib']
    return (
        <tr
            className={'cursor-pointer event-row ' + (highlightEvents[event.id] && 'event-row-new')}
            onClick={() => setSelectedEvent(selectedEvent !== event.id ? event.id : false)}
        >
            <td>
                {eventNameMap(event)}
                {event.elements.length > 0 && (
                    <pre style={{ marginBottom: 0, display: 'inline' }}>&lt;{event.elements[0].tag_name}&gt;</pre>
                )}
                {event.elements.length > 0 && event.elements[0].text && ' with text "' + event.elements[0].text + '"'}
            </td>
            <td>
                <Link to={'/person/' + encodeURIComponent(event.distinct_id)} className="ph-no-capture">
                    {event.person}
                </Link>
            </td>
            {params.map(paramRequest => {
                let param = paramRequest
                let value = event.properties[param]

                if (param === '$current_url' && !value) {
                    param = '$screen'
                    value = event.properties[param]
                }

                return (
                    <td key={param} title={value}>
                        {filtersEnabled ? (
                            <FilterPropertyLink
                                property={param}
                                value={event.properties[param]}
                                filters={{ properties }}
                            />
                        ) : (
                            <Property value={event.properties[param]} />
                        )}
                    </td>
                )
            })}
            <td>{moment(event.timestamp).fromNow()}</td>
        </tr>
    )
}
