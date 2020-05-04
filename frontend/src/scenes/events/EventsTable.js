import React, { Component } from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'

import { fromParams, Loading, toParams } from 'lib/utils'
import api from 'lib/api'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { EventDetails } from 'scenes/events/EventDetails'
import { EventRow } from 'scenes/events/EventRow'
import { NoItems } from 'scenes/events/NoItems'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { Spin } from 'antd'

export function EventsTable({ fixedFilters }) {
    const { properties, events, isLoading, hasNext, isLoadingNext, eventSelected } = useValues(
        eventsTableLogic({ fixedFilters })
    )
    const { setProperties, updateProperty, setEventSelected, fetchNextEvents } = useActions(
        eventsTableLogic({ fixedFilters })
    )

    const newEvents = []
    const highlightEvents = []
    const onTimestampHeaderClick = () => {}
    const clickLoadNewEvents = () => {}

    return (
        <div className="events">
            <PropertyFilters propertyFilters={properties} pageKey="EventsTable" onChange={setProperties} />
            <table className="table" style={{ position: 'relative' }}>
                {isLoading && <Loading />}
                <thead>
                    <tr>
                        <th>Event</th>
                        <th>Person</th>
                        <th>Path / Screen</th>
                        <th>Source</th>
                        <th onClick={onTimestampHeaderClick}>
                            When <i className="fi flaticon-sort" />
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {isLoading && (
                        <div className="loading">
                            <div />
                        </div>
                    )}
                    <tr
                        className={'event-new-events ' + (newEvents.length > 0 ? 'show' : 'hide')}
                        onClick={clickLoadNewEvents}
                    >
                        <td colSpan="5">
                            <div>There are {newEvents.length} new events. Click here to load them.</div>
                        </td>
                    </tr>
                    {!events || events.length === 0 ? <NoItems events={events} /> : null}
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
                                    highlightEvents={highlightEvents}
                                    eventSelected={eventSelected}
                                    properties={properties}
                                    setEventSelected={setEventSelected}
                                    setFilter={updateProperty}
                                />
                                {eventSelected === event.id && (
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
                    {isLoadingNext ? <Spin /> : 'Load more events11'}
                </button>
            </div>
            <div style={{ marginTop: '5rem' }} />
        </div>
    )
}

export class EventsTableOld extends Component {
    constructor(props) {
        super(props)

        let params = fromParams()
        this.state = {
            properties: params.properties ? JSON.parse(params.properties) : {},
            newEvents: [],
            loading: true,
            highlightEvents: [],
            orderBy: {
                timestamp: '-timestamp',
            },
        }
        this.fetchEvents = this.fetchEvents.bind(this)
        this.pollEvents = this.pollEvents.bind(this)
        this.clickNext = this.clickNext.bind(this)
        this.clickLoadNewEvents = this.clickLoadNewEvents.bind(this)
        this.pollTimeout = 5000
        this.fetchEvents()
        this.onTimestampHeaderClick = this.onTimestampHeaderClick.bind(this)
    }

    onTimestampHeaderClick() {
        this.setState(
            prevState => ({
                orderBy: {
                    ...prevState.orderBy,
                    timestamp: prevState.orderBy.timestamp === '-timestamp' ? 'timestamp' : '-timestamp',
                },
            }),
            () => this.fetchEvents()
        )
    }

    pollEvents() {
        // Poll events when they are ordered in ascending order based on timestamp
        if (this.state.orderBy.timestamp === '-timestamp') {
            let params = {
                properties: this.state.properties,
                ...this.props.fixedFilters,
                orderBy: Object.values(this.state.orderBy),
            }
            if (this.state.events[0])
                params['after'] = this.state.events[0].timestamp
                    ? this.state.events[0].timestamp
                    : this.state.events[0].event.timestamp
            api.get('api/event/?' + toParams(params)).then(events => {
                this.setState({ newEvents: events.results, highlightEvents: [] })
                this.poller = setTimeout(this.pollEvents, this.pollTimeout)
            })
        }
    }
    componentWillUnmount() {
        clearTimeout(this.poller)
    }

    clickLoadNewEvents() {
        let { newEvents, events } = this.state
        this.setState({
            newEvents: [],
            events: [...newEvents, ...events],
            highlightEvents: newEvents.map(event => event.id),
        })
    }
}
