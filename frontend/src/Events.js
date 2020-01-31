import React, { Component } from 'react';
import api from './Api';
import moment from 'moment';
import { Link } from 'react-router-dom';
import { toParams, fromParams, colors } from './utils';
import PropTypes from 'prop-types';


export class EventDetails extends Component {
    constructor(props) {
        super(props)
        this.state = {selected: 'properties'}
    }
    render() {
        return <div className='row'>
            <div className='col-3'>
                <div className="nav flex-column nav-pills" id="v-pills-tab" role="tablist" aria-orientation="vertical">
                    <a className={"cursor-pointer nav-link " + (this.state.selected == 'properties' && 'active')} onClick={() => this.setState({selected: 'properties'})}>Properties</a>
                    <a className={"cursor-pointer nav-link " + (this.state.selected == 'elements' && 'active')} onClick={() => this.setState({selected: 'elements'})}>Elements</a>
                </div>
            </div>
            <div className='col-9'>
                {this.state.selected == 'properties' ? <div className='d-flex flex-wrap flex-column' style={{height: 200}}>
                    {Object.keys(this.props.event.properties).sort().map((key) =>
                        <div style={{flex: '0 1 '}} key={key}>
                            <strong>{key}:</strong>
                            {this.props.event.properties[key]}
                    </div>)}
                </div> : <div>
                    {JSON.stringify(this.props.event.elements)}
                </div>}
            </div>
        </div>
    }
}

export class EventsTable extends Component {
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
        this.fetchEvents();
    }
    fetchEvents() {
        let params = toParams({
            ...this.state.filters,
            ...this.props.fixedFilters
        })
        clearTimeout(this.poller)
        api.get('api/event/?' + params).then((events) => {
            this.setState({events: events.results});
            this.poller = setTimeout(this.pollEvents, this.pollTimeout);
        })
    }
    pollEvents() {
        let params = { 
            ...this.state.filters,
            ...this.props.fixedFilters,
        }
        if(this.state.events[0]) params['after'] = this.state.events[0].timestamp ? this.state.events[0].timestamp : this.state.events[0].event.timestamp
        api.get('api/event/?' + toParams(params)).then((events) => {
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
            <div className='events'>
                <this.Filters />
                <table className='table'>
                    <tbody>
                        <tr><th>Event</th><th>Person</th><th>Path</th><th>When</th></tr>
                        {this.state.events && this.state.events.map((event, index) => [
                            index > 0 && !moment(event.timestamp).isSame(this.state.events[index - 1].timestamp, 'day') && <tr key={event.id + '_time'}><td colSpan="4" className='event-day-separator'>{moment(event.timestamp).format('LL')}</td></tr>,
                            <tr key={event.id} className={'cursor-pointer event-row ' + (this.state.newEvents.indexOf(event.id) > -1 && 'event-row-new')} onClick={() => this.setState({eventSelected: this.state.eventSelected != event.id ? event.id : false})}>
                                <td>
                                    {event.properties.$event_type == 'click' ? 'clicked' : event.event}
                                    {event.elements.length > 0 && ' a ' + event.elements[0].tag_name + ' element '}
                                    {event.elements.length > 0 && event.elements[0].$el_text && ' with text ' + event.elements[0].$el_text}
                                </td>
                                <td><Link to={'/person/' + event.properties.distinct_id}>{event.person}</Link></td>
                                {params.map((param) => <td key={param} title={event.properties[param]}>
                                    <this.FilterLink property={param} value={event.properties[param]} />
                                </td>)}
                                <td>{moment(event.timestamp).fromNow()}</td>
                                {/* <td><pre>{JSON.stringify(event)}</pre></td> */}
                            </tr>,
                            this.state.eventSelected == event.id && <tr key={event.id + '_open'}>
                                <td colSpan="4">
                                    <EventDetails event={event} />
                                </td>
                            </tr>
                        ])}
                    </tbody>
                </table>
            </div>
        )
    }
}
EventsTable.propTypes = {
    fixedFilters: PropTypes.object,
    history: PropTypes.object.isRequired
}

export default class Events extends Component {
    render() {
        return <EventsTable {...this.props} />
    }
}
