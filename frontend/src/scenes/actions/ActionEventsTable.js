import React, { Component } from 'react'
import { fromParams, Loading, toParams } from '../../lib/utils'
import api from '../../lib/api'
import { Link } from 'react-router-dom'
import { PropertyFilters } from '../../lib/components/PropertyFilters/PropertyFilters'
import moment from 'moment'
import { EventDetails } from '../events/EventDetails'
import PropTypes from 'prop-types'
import { FilterLink } from '../../lib/components/FilterLink'

export class ActionEventsTable extends Component {
    constructor(props) {
        super(props)

        let params = fromParams()
        this.state = {
            properties: params.properties ? JSON.parse(params.properties) : {},
            newEvents: [],
            loading: true,
        }
        this.fetchEvents = this.fetchEvents.bind(this)
        this.pollEvents = this.pollEvents.bind(this)
        this.pollTimeout = 5000
        this.fetchEvents(this)
    }
    fetchEvents() {
        let params = toParams({
            properties: this.state.properties,
            ...this.props.fixedFilters,
        })
        clearTimeout(this.poller)
        api.get('api/event/actions/?' + params).then(events => {
            this.setState({ events: events.results, loading: false })
            this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        })
    }
    pollEvents() {
        let params = {
            ...this.props.fixedFilters,
            properties: this.state.properties,
        }
        if (this.state.events[0])
            params['after'] = this.state.events[0].event.timestamp
        api.get('api/event/actions/?' + toParams(params)).then(events => {
            this.setState({
                events: [...events.results, ...this.state.events],
                newEvents: events.results.map(event => event.id),
            })
            this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        })
    }
    componentWillUnmount() {
        clearTimeout(this.poller)
    }
    render() {
        let params = ['$current_url']
        let { loading, properties, events } = this.state
        return (
            <div className="events">
                <PropertyFilters
                    propertyFilters={properties}
                    onChange={properties =>
                        this.setState({ properties }, this.fetchEvents)
                    }
                />
                <table className="table">
                    <tbody>
                        <tr>
                            <th scope="col">Action ID</th>
                            <th scope="col">User</th>
                            <th scope="col">Path</th>
                            <th scope="col">Date</th>
                            <th scope="col">Browser</th>
                        </tr>
                        {loading && <Loading />}
                        {events && events.length == 0 && (
                            <tr>
                                <td colSpan="5">
                                    We didn't find any events matching any
                                    actions. You can either{' '}
                                    <Link to="/actions">
                                        set up some actions
                                    </Link>{' '}
                                    or{' '}
                                    <Link to="/setup">
                                        integrate PostHog in your app
                                    </Link>
                                    .
                                </td>
                            </tr>
                        )}
                        {events &&
                            events.map((action, index) => [
                                index > 0 &&
                                    !moment(action.event.timestamp).isSame(
                                        events[index - 1].event.timestamp,
                                        'day'
                                    ) && (
                                        <tr key={action.event.id + '_time'}>
                                            <td
                                                colSpan="5"
                                                className="event-day-separator"
                                            >
                                                {moment(
                                                    action.event.timestamp
                                                ).format('LL')}
                                            </td>
                                        </tr>
                                    ),
                                <tr
                                    key={action.id}
                                    className={
                                        'cursor-pointer event-row ' +
                                        (this.state.newEvents.indexOf(
                                            action.event.id
                                        ) > -1 && 'event-row-new')
                                    }
                                    onClick={() =>
                                        this.setState({
                                            eventSelected:
                                                this.state.eventSelected !=
                                                action.id
                                                    ? action.id
                                                    : false,
                                        })
                                    }
                                >
                                    <td>{action.action.name}</td>
                                    <td>
                                        <Link
                                            to={
                                                '/person/' +
                                                action.event.distinct_id
                                            }
                                        >
                                            {action.event.person}
                                        </Link>
                                    </td>
                                    {params.map(param => (
                                        <td
                                            key={param}
                                            title={
                                                action.event.properties[param]
                                            }
                                        >
                                            <FilterLink
                                                property={param}
                                                value={
                                                    action.event.properties[
                                                        param
                                                    ]
                                                }
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
                                    <td>
                                        {moment(
                                            action.event.timestamp
                                        ).fromNow()}
                                    </td>
                                    <td>
                                        {action.event.properties.$browser}{' '}
                                        {
                                            action.event.properties
                                                .$browser_version
                                        }{' '}
                                        - {action.event.properties.$os}
                                    </td>
                                </tr>,
                                this.state.eventSelected == action.id && (
                                    <tr key={action.id + '_open'}>
                                        <td colSpan="4">
                                            <EventDetails
                                                event={action.event}
                                            />
                                        </td>
                                    </tr>
                                ),
                            ])}
                    </tbody>
                </table>
            </div>
        )
    }
}
ActionEventsTable.propTypes = {
    fixedFilters: PropTypes.object,
    history: PropTypes.object.isRequired,
}
