import React, { Component } from 'react'
import { fromParams, toParams } from '../../lib/utils'
import api from '../../lib/api'
import { Link } from 'react-router-dom'
import moment from 'moment'
import { PropertyFilters } from '../../lib/components/PropertyFilters/PropertyFilters'
import { FilterLink } from '../../lib/components/FilterLink'
import { EventDetails } from './EventDetails'
import PropTypes from 'prop-types'

let eventNameMap = event => {
    if (event.properties.$event_type == 'click') return 'clicked '
    if (event.properties.$event_type == 'change') return 'typed something into '
    if (event.properties.$event_type == 'submit') return 'submitted '
    return event.event
}

export class EventsTable extends Component {
    constructor(props) {
        super(props)

        let params = fromParams()
        this.state = {
            properties: params.properties ? JSON.parse(params.properties) : {},
            newEvents: [],
            loading: true,
            highlightEvents: [],
        }
        this.fetchEvents = this.fetchEvents.bind(this)
        this.pollEvents = this.pollEvents.bind(this)
        this.clickNext = this.clickNext.bind(this)
        this.EventRow = this.EventRow.bind(this)
        this.clickLoadNewEvents = this.clickLoadNewEvents.bind(this)
        this.pollTimeout = 5000
        this.fetchEvents()
    }
    fetchEvents() {
        let params = {}
        if (Object.keys(this.state.properties).length > 0)
            params.properties = this.state.properties
        this.props.history.push({
            pathname: this.props.history.location.pathname,
            search: toParams(params),
        })
        if (!this.state.loading) this.setState({ loading: true })
        clearTimeout(this.poller)
        params = toParams({
            ...params,
            ...this.props.fixedFilters,
        })
        api.get('api/event/?' + params).then(events => {
            this.setState({
                events: events.results,
                hasNext: events.next,
                loading: false,
            })
            this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        })
    }
    pollEvents() {
        let params = {
            properties: this.state.properties,
            ...this.props.fixedFilters,
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
    componentWillUnmount() {
        clearTimeout(this.poller)
    }

    clickNext() {
        let { events } = this.state
        let params = toParams({
            properties: this.state.properties,
            ...this.props.fixedFilters,
            before: events[events.length - 1].timestamp,
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
    EventRow(props) {
        let { event } = props
        let { highlightEvents, eventSelected, properties } = this.state
        let params = ['$current_url', '$lib']
        return (
            <tr
                className={
                    'cursor-pointer event-row ' +
                    (highlightEvents.indexOf(event.id) > -1 && 'event-row-new')
                }
                onClick={() =>
                    this.setState({
                        eventSelected:
                            eventSelected != event.id ? event.id : false,
                    })
                }
            >
                <td>
                    {eventNameMap(event)}
                    {event.elements.length > 0 && (
                        <pre style={{ marginBottom: 0, display: 'inline' }}>
                            &lt;{event.elements[0].tag_name}&gt;
                        </pre>
                    )}
                    {event.elements.length > 0 &&
                        event.elements[0].text &&
                        ' with text "' + event.elements[0].text + '"'}
                </td>
                <td>
                    <Link
                        to={'/person/' + encodeURIComponent(event.distinct_id)}
                        className="ph-no-capture"
                    >
                        {event.person}
                    </Link>
                </td>
                {params.map(param => (
                    <td key={param} title={event.properties[param]}>
                        <FilterLink
                            property={param}
                            value={event.properties[param]}
                            filters={properties}
                            onClick={(key, value) =>
                                this.setState(
                                    {
                                        properties: {
                                            ...properties,
                                            [key]: value,
                                        },
                                    },
                                    this.fetchEvents
                                )
                            }
                        />
                    </td>
                ))}
                <td>{moment(event.timestamp).fromNow()}</td>
            </tr>
        )
    }
    NoItems(props) {
        if (!props.events || props.events.length > 0) return null
        return (
            <tr>
                <td colSpan="4">
                    You don't have any items here. If you haven't integrated
                    PostHog yet,{' '}
                    <Link to="/setup">
                        click here to set PostHog up on your app
                    </Link>
                </td>
            </tr>
        )
    }
    render() {
        let {
            properties,
            events,
            loading,
            hasNext,
            newEvents,
            highlightEvents,
        } = this.state
        return (
            <div className="events">
                <PropertyFilters
                    propertyFilters={properties}
                    onChange={properties =>
                        this.setState({ properties }, this.fetchEvents)
                    }
                />
                <table className="table" style={{ position: 'relative' }}>
                    {loading && (
                        <div className="loading-overlay">
                            <div></div>
                        </div>
                    )}
                    <thead>
                        <tr>
                            <th>Event</th>
                            <th>Person</th>
                            <th>Path</th>
                            <th>Source</th>
                            <th>When</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && (
                            <div className="loading">
                                <div></div>
                            </div>
                        )}
                        <tr
                            className={
                                'event-new-events ' +
                                (this.state.newEvents.length > 0
                                    ? 'show'
                                    : 'hide')
                            }
                            onClick={this.clickLoadNewEvents}
                        >
                            <td colSpan="5">
                                <div>
                                    There are {newEvents.length} new events.
                                    Click here to load them.
                                </div>
                            </td>
                        </tr>
                        <this.NoItems events={events} />
                        {this.state.events &&
                            this.state.events.map((event, index) => [
                                index > 0 &&
                                    !moment(event.timestamp).isSame(
                                        events[index - 1].timestamp,
                                        'day'
                                    ) && (
                                        <tr key={event.id + '_time'}>
                                            <td
                                                colSpan="5"
                                                className="event-day-separator"
                                            >
                                                {moment(event.timestamp).format(
                                                    'LL'
                                                )}
                                            </td>
                                        </tr>
                                    ),
                                <this.EventRow event={event} key={event.id} />,
                                this.state.eventSelected == event.id && (
                                    <tr key={event.id + '_open'}>
                                        <td colSpan="5">
                                            <EventDetails event={event} />
                                        </td>
                                    </tr>
                                ),
                            ])}
                    </tbody>
                </table>
                {hasNext && (
                    <button
                        className="btn btn-primary"
                        onClick={this.clickNext}
                        style={{ margin: '2rem auto 15rem', display: 'block' }}
                    >
                        Load more events
                    </button>
                )}
                <div style={{ marginTop: '15rem' }}></div>
            </div>
        )
    }
}
EventsTable.propTypes = {
    fixedFilters: PropTypes.object,
    history: PropTypes.object.isRequired,
}
