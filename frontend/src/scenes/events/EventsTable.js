import React, { Component } from 'react'
import { kea, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import moment from 'moment'

import { fromParams, Loading, toParams } from 'lib/utils'
import api from 'lib/api'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { EventDetails } from 'scenes/events/EventDetails'
import { EventRow } from 'scenes/events/EventRow'
import { NoItems } from 'scenes/events/NoItems'

const addQuestion = search => (search ? `?${search}` : '')

// props: fixedFilters
const eventsTableLogic = kea({
    actions: () => ({
        setProperties: properties => ({ properties }),
        updateProperty: (key, value) => ({ key, value }),
        fetchEvents: true,
        fetchEventsSuccess: (events, hasNext) => ({ events, hasNext }),
        pollEvents: true,
        setEventSelected: eventSelected => ({ eventSelected }),
    }),

    reducers: () => ({
        properties: [
            {},
            {
                setProperties: (_, { properties }) => properties,
                updateProperty: (state, { key, value }) => ({ ...state, [key]: value }),
            },
        ],
        isLoading: [
            false,
            {
                fetchEvents: () => true,
                fetchEventsSuccess: () => false,
            },
        ],
        events: [
            [],
            {
                fetchEventsSuccess: (_, { events }) => events,
            },
        ],
        hasNext: [
            false,
            {
                fetchEventsSuccess: (_, { hasNext }) => hasNext,
            },
        ],
        orderBy: ['-timestamp', {}],
        eventSelected: [
            null,
            {
                setEventSelected: (_, { eventSelected }) => eventSelected,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        urlParams: [
            () => [selectors.properties],
            properties => {
                if (Object.keys(properties).length > 0) {
                    return '?' + toParams({ properties })
                } else {
                    return ''
                }
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: [actions.fetchEvents],
    }),

    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return `${router.values.location.pathname}${values.urlParams}`
        },
        updateProperty: () => {
            return `${router.values.location.pathname}${values.urlParams}`
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '/events': () => {
            const { urlParams } = values
            const newFilters = fromParams()
            const newUrlParams = addQuestion(toParams(newFilters))

            if (newUrlParams !== urlParams) {
                actions.setProperties(newFilters.properties ? JSON.parse(newFilters.properties) : {})
            }
        },
    }),

    listeners: ({ actions, values, props }) => ({
        setProperties: () => {
            actions.fetchEvents()
        },
        updateProperty: () => {
            actions.fetchEvents()
        },
        fetchEvents: async (_, breakpoint) => {
            // clearTimeout(this.poller)

            const urlParams = toParams({
                properties: values.properties,
                ...(props.fixedFilters || {}),
                orderBy: [values.orderBy],
            })

            const events = await api.get('api/event/?' + urlParams)
            breakpoint()
            actions.fetchEventsSuccess(events.results, events.next)
            // this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        },
    }),
})

export function EventsTable({ fixedFilters }) {
    const { properties, events, isLoading, hasNext, eventSelected } = useValues(eventsTableLogic({ fixedFilters }))
    const { setProperties, updateProperty, setEventSelected } = useActions(eventsTableLogic({ fixedFilters }))

    const newEvents = []
    const highlightEvents = []
    const onTimestampHeaderClick = () => {}
    const clickLoadNewEvents = () => {}
    const clickNext = () => {}

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
            {hasNext && (
                <button
                    className="btn btn-primary"
                    onClick={clickNext}
                    style={{ margin: '2rem auto 15rem', display: 'block' }}
                >
                    Load more events
                </button>
            )}
            <div style={{ marginTop: '15rem' }} />
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

    clickNext() {
        let { events } = this.state
        let params = toParams({
            properties: this.state.properties,
            ...this.props.fixedFilters,
            before: events[events.length - 1].timestamp,
            orderBy: Object.values(this.state.orderBy),
        })
        clearTimeout(this.poller)
        this.setState({ hasNext: false })
        api.get('api/event/?' + params).then(olderEvents => {
            this.setState({
                events: [...events, ...olderEvents.results],
                hasNext: olderEvents.next,
                loading: false,
            })
            this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        })
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
