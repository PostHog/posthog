import React from 'react'
import moment from 'moment'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'
import { Link } from 'lib/components/Link'

const eventNameMap = event => {
    if (event.properties.$event_type === 'click') return 'clicked '
    if (event.properties.$event_type === 'change') return 'typed something into '
    if (event.properties.$event_type === 'submit') return 'submitted '
    return event.event
}

export function EventRow({
    event,
    highlightEvents,
    selectedEvent,
    properties,
    search,
    setSelectedEvent,
    filtersEnabled,
    showLinkToPerson,
    index,
}) {
    let params = ['$current_url', '$lib']
    return (
        <tr
            className={'cursor-pointer event-row ' + (highlightEvents[event.id] && 'event-row-new')}
            onClick={() => setSelectedEvent(selectedEvent !== event.id ? event.id : false)}
            data-attr={'event-row-' + index}
        >
            <td data-attr={'event-name-' + index}>
                {eventNameMap(event)}
                {event.elements.length > 0 && (
                    <pre style={{ marginBottom: 0, display: 'inline' }}>&lt;{event.elements[0].tag_name}&gt;</pre>
                )}
                {event.elements.length > 0 && event.elements[0].text && ' with text "' + event.elements[0].text + '"'}
            </td>
            <td>
                {showLinkToPerson ? (
                    <Link to={`/person/${encodeURIComponent(event.distinct_id)}${search}`} className="ph-no-capture">
                        {event.person}
                    </Link>
                ) : (
                    event.person
                )}
            </td>
            {params.map(paramRequest => {
                let param = paramRequest
                let value = event.properties[param]

                if (param === '$current_url' && !value) {
                    param = '$screen_name'
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
