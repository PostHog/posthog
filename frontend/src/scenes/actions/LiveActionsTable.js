import React, { Fragment } from 'react'
import moment from 'moment'

import { TableRowLoading } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'

import { EventDetails } from 'scenes/events/EventDetails'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { useActions, useValues } from 'kea'

export function LiveActionsTable({ fixedFilters }) {
    const logic = eventsTableLogic({ fixedFilters, apiUrl: 'api/event/actions/', live: true })
    const { properties, events, isLoading, selectedEvent, highlightEvents } = useValues(logic)
    const { setSelectedEvent } = useActions(logic)

    let params = ['$current_url']
    return (
        <div className="events">
            <PropertyFilters pageKey="LiveActionsTable" propertyFilters={properties} />
            <table className="table" style={{ position: 'relative' }}>
                <tbody>
                    <tr>
                        <th scope="col">Action ID</th>
                        <th scope="col">User</th>
                        <th scope="col">Path</th>
                        <th scope="col">Date</th>
                        <th scope="col">Browser</th>
                    </tr>
                    {isLoading && <TableRowLoading colSpan={5} />}
                    {events && events.length === 0 && (
                        <tr>
                            <td colSpan="5">
                                We didn't find any events matching any actions. You can either{' '}
                                <Link to="/actions">set up some actions</Link> or{' '}
                                <Link to="/setup">integrate PostHog in your app</Link>.
                            </td>
                        </tr>
                    )}
                    {events &&
                        events.map((action, index) => (
                            <Fragment key={action.id}>
                                {index > 0 &&
                                    !moment(action.event.timestamp).isSame(
                                        events[index - 1].event.timestamp,
                                        'day'
                                    ) && (
                                        <tr>
                                            <td colSpan="5" className="event-day-separator">
                                                {moment(action.event.timestamp).format('LL')}
                                            </td>
                                        </tr>
                                    )}
                                <tr
                                    className={
                                        'cursor-pointer event-row' +
                                        (highlightEvents[action.id] ? ' event-row-new' : '')
                                    }
                                    onClick={() => setSelectedEvent(selectedEvent === action.id ? null : action.id)}
                                >
                                    <td>{action.action.name}</td>
                                    <td>
                                        <Link to={`/person/${action.event.distinct_id}`}>{action.event.person}</Link>
                                    </td>
                                    {params.map(param => (
                                        <td key={param} title={action.event.properties[param]}>
                                            <FilterPropertyLink
                                                property={param}
                                                value={action.event.properties[param]}
                                                filters={{ properties }}
                                            />
                                        </td>
                                    ))}
                                    <td>{moment(action.event.timestamp).fromNow()}</td>
                                    <td>
                                        {action.event.properties.$browser} {action.event.properties.$browser_version} -{' '}
                                        {action.event.properties.$os}
                                    </td>
                                </tr>
                                {selectedEvent === action.id && (
                                    <tr>
                                        <td colSpan="4">
                                            <EventDetails event={action.event} />
                                        </td>
                                    </tr>
                                )}
                            </Fragment>
                        ))}
                </tbody>
            </table>
        </div>
    )
}
