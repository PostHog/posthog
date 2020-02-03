import React, { Component } from 'react';
import api from './Api';
import moment from 'moment';
import { Link } from 'react-router-dom';
import { toParams, fromParams, colors } from './utils';
import PropTypes from 'prop-types';
import { EventDetails } from './Events';


export class ActionEventsTable extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            filters: fromParams(),
            newEvents: []
        }
        this.fetchEvents = this.fetchEvents.bind(this);
        this.FilterLink = this.FilterLink.bind(this);
        this.Filters = this.Filters.bind(this);
        this.pollEvents = this.pollEvents.bind(this);
        this.pollTimeout = 5000;
        this.fetchEvents(this);
    }
    fetchEvents() {
        let params = toParams({
            ...this.state.filters,
            ...this.props.fixedFilters
        })
        clearTimeout(this.poller)
        api.get('api/event/actions/?' + params).then((events) => {
            this.setState({events: events.results});
            this.poller = setTimeout(this.pollEvents, this.pollTimeout);
        })
    }
    pollEvents() {
        let params = { 
            ...this.state.filters,
            ...this.props.fixedFilters,
        }
        if(this.state.events[0]) params['after'] = this.state.events[0].event.timestamp
        api.get('api/event/actions/?' + toParams(params)).then((events) => {
            this.setState({events: [...events.results, ...this.state.events], newEvents: events.results.map((event) => event.id)});
            this.poller = setTimeout(this.pollEvents, this.pollTimeout);
        })
    }
    componentWillUnmount() {
        clearTimeout(this.poller)
    }
    FilterLink(props) {
        let filters = {...this.state.filters};
        filters[props.property] = props.value;
        return <Link
            to={{pathname: this.props.history.pathname, search: toParams(filters)}}
            onClick={(event) => {
                this.state.filters[props.property] = props.value;
                this.setState({filters: this.state.filters});
                this.fetchEvents();
            }}
            >{typeof props.value === 'object' ? JSON.stringify(props.value) : props.value}</Link>
    }
    Filters() {
        return <div style={{marginBottom: '2rem'}}>
            {Object.keys(this.state.filters).map((filter, index) => <div className={'badge badge-' + colors[index]} style={{marginRight: 8, padding: 8}}>
                <strong>{filter}:</strong> {this.state.filters[filter]}
                <button type="button" className="close" aria-label="Close" onClick={() => {
                    delete this.state.filters[filter];
                    this.setState({filters: this.state.filters});
                    this.fetchEvents();
                    this.props.history.push(this.props.history.location.pathname + '?' + toParams(this.state.filters))
                }}>
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>)}
        </div>
    }
    render() {
        let params = ['$current_url']
        return (
            <div class='events'>
                <this.Filters />
                <table className='table'>
                    <tbody>
                        <tr>
                            <th scope="col">Action ID</th>
                            <th scope="col">Type</th>
                            <th scope="col">User</th>
                            <th scope="col">Date</th>
                            <th scope="col">Browser</th>
                            <th scope="col">City</th>
                            <th scope="col">Country</th>
                        </tr>

                        {this.state.events && this.state.events.length == 0 && <tr><td colSpan="7">We didn't find any events matching any actions. You can either <Link to='/actions'>set up some actions</Link> or <Link to='/setup'>integrate PostHog in your app</Link>.</td></tr>}
                        {this.state.events && this.state.events.map((action, index) => [
                            index > 0
                                && !moment(action.event.timestamp).isSame(this.state.events[index - 1].event.timestamp, 'day')
                                && <tr key={action.event.id + '_time'}>
                                    <td colSpan="4" className='event-day-separator'>
                                        {moment(action.event.timestamp).format('LL')}
                                    </td>
                                </tr>,
                            <tr key={action.id} className={'cursor-pointer event-row ' + (this.state.newEvents.indexOf(action.event.id) > -1 && 'event-row-new')} onClick={() => this.setState({eventSelected: this.state.eventSelected != action.id ? action.id : false})}>
                                <td>
                                    {action.action.name}
                                </td>
                                <td><Link to={'/person/' + action.event.distinct_id}>{action.event.distinct_id}</Link></td>
                                {params.map((param) => <td key={param} title={action.event.properties[param]}>
                                    <this.FilterLink property={param} value={action.event.properties[param]} />
                                </td>)}
                                <td>{moment(action.event.timestamp).fromNow()}</td>
                                <td>{action.event.properties.$browser} {action.event.properties.$browser_version} - {action.event.properties.$os}</td>
                                {/* <td><pre>{JSON.stringify(event)}</pre></td> */}
                            </tr>,
                            this.state.eventSelected == action.id && <tr key={action.id + '_open'}>
                                <td colSpan="4">
                                    <EventDetails event={action.event} />
                                </td>
                            </tr>
                        ])}
                    </tbody>
                </table>
            </div>
        )
    }
}
ActionEventsTable.propTypes = {
    fixedFilters: PropTypes.object,
    history: PropTypes.object.isRequired
}

export default class ActionEvents extends Component {
    render() {
        return <ActionEventsTable {...this.props} />
    }
}
