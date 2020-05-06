import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'

import { TableRowLoading } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { EventDetails } from 'scenes/events/EventDetails'
import { EventRow } from 'scenes/events/EventRow'
import { NoItems } from 'scenes/events/NoItems'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { Spin } from 'antd'
import { router } from 'kea-router'

export function EventsTable({ fixedFilters, filtersEnabled = true }) {
    const logic = eventsTableLogic({ fixedFilters })
    const {
        properties,
        events,
        isLoading,
        hasNext,
        isLoadingNext,
        selectedEvent,
        newEvents,
        highlightEvents,
    } = useValues(logic)
    const { updateProperty, setSelectedEvent, fetchNextEvents, flipSort, prependNewEvents } = useActions(logic)
    const {
        location: { search },
    } = useValues(router)

    const showLinkToPerson = !fixedFilters?.person_id

    return (
        <div className="events">
            {filtersEnabled ? <PropertyFilters pageKey="EventsTable" /> : null}
            <table className="table" style={{ position: 'relative' }}>
                <thead>
                    <tr>
                        <th>Event</th>
                        <th>Person</th>
                        <th>Path / Screen</th>
                        <th>Source</th>
                        <th onClick={flipSort}>
                            When <i className="fi flaticon-sort" />
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {isLoading && <TableRowLoading colSpan={5} asOverlay={events.length > 0} />}
                    <tr
                        className={'event-new-events ' + (newEvents.length > 0 ? 'show' : 'hide')}
                        onClick={() => prependNewEvents(newEvents)}
                    >
                        <td colSpan="5">
                            <div>There are {newEvents.length} new events. Click here to load them.</div>
                        </td>
                    </tr>
                    {!events || events.length === 0 ? <NoItems /> : null}
                    {events &&
                        events.map((event, index) => (
                            <React.Fragment key={event.id}>
                                {index > 0 && !moment(event.timestamp).isSame(events[index - 1].timestamp, 'day') && (
                                    <tr>
                                        <td colSpan="5" className="event-day-separator">
                                            {moment(event.timestamp).format('LL')}
                                        </td>
                                    </tr>
                                )}
                                <EventRow
                                    event={event}
                                    search={search}
                                    highlightEvents={highlightEvents}
                                    selectedEvent={selectedEvent}
                                    properties={properties}
                                    setSelectedEvent={setSelectedEvent}
                                    setFilter={updateProperty}
                                    filtersEnabled={filtersEnabled}
                                    showLinkToPerson={showLinkToPerson}
                                />
                                {selectedEvent === event.id && (
                                    <tr>
                                        <td colSpan="5">
                                            <EventDetails event={event} />
                                        </td>
                                    </tr>
                                )}
                            </React.Fragment>
                        ))}
                </tbody>
            </table>
            <div
                style={{
                    visibility: hasNext || isLoadingNext ? 'visible' : 'hidden',
                    margin: '2rem auto 5rem',
                    textAlign: 'center',
                }}
            >
                <button className="btn btn-primary" onClick={fetchNextEvents}>
                    {isLoadingNext ? <Spin /> : 'Load more events'}
                </button>
            </div>
            <div style={{ marginTop: '5rem' }} />
        </div>
    )
}
