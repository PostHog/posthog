import React from 'react'
import { Link } from 'react-router-dom'
import moment from 'moment'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'

let eventNameMap = event => {
    if (event.properties.$event_type === 'click') return 'clicked '
    if (event.properties.$event_type === 'change') return 'typed something into '
    if (event.properties.$event_type === 'submit') return 'submitted '
    return event.event
}

export function EventRow({ event, highlightEvents, eventSelected, properties, setEventSelected, setFilter }) {
    let params = ['$current_url', '$lib']
    return (
        <tr
            className={'cursor-pointer event-row ' + (highlightEvents.indexOf(event.id) > -1 && 'event-row-new')}
            onClick={() => setEventSelected(eventSelected !== event.id ? event.id : false)}
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
                        <FilterPropertyLink property={param} value={event.properties[param]} filters={{ properties }} />
                    </td>
                )
            })}
            <td>{moment(event.timestamp).fromNow()}</td>
        </tr>
    )
}
