import React, { Component } from 'react';
import api from './Api';
import moment from 'moment';
import { Link } from 'react-router-dom';
import { toParams, fromParams, colors } from './utils';
import PropTypes from 'prop-types';
import PropertyFilter from './PropertyFilter';

let eventNameMap = (event) => {
    if(event.properties.$event_type == 'click') return 'clicked ';
    if(event.properties.$event_type == 'change') return 'typed something into ';
    if(event.properties.$event_type == 'submit') return 'submitted ';
    return event.event
}


export class EventDetails extends Component {
    constructor(props) {
        super(props)
        this.state = {selected: 'properties'}
        this.ShowElements = this.ShowElements.bind(this);
    }
    indent(n) {
        return Array(n).fill().map(() => <span>&nbsp;&nbsp;&nbsp;&nbsp;</span>)
    }
    ShowElements(props) {
        let { elements } = props;
        return <div>
            {elements.map((element, index) => (
                <pre className='code' style={{margin: 0, padding: 0, borderRadius: 0, ...(index == elements.length -1 ? {backgroundColor: 'var(--blue)'} : {})}}>
                    {this.indent(index)}
                    &lt;{element.tag_name} 

                    {element.attr_id && ' id="' + element.attr_id + '"'}
                    {
                        Object.entries(element.attributes)
                            .map(([key, value]) => <span> {key.replace('attr__', '')}="{value}"</span>)
                    }
                    &gt;{element.text}
                    {index == elements.length - 1 && <span>&lt;/{element.tag_name}&gt;</span>}
                </pre>
            ))}
            {[...elements].reverse().slice(1).map((element, index) => <pre className='code' style={{margin: 0, padding: 0, borderRadius: 0}}>
                {this.indent(elements.length - index - 2)}
                &lt;/{element.tag_name}&gt;
            </pre>)}
        </div>
    }
    render() {
        let { event } = this.props;
        let elements = [...event.elements].reverse();
        return <div className='row'>
            <div className='col-2'>
                <div className="nav flex-column nav-pills" id="v-pills-tab" role="tablist" aria-orientation="vertical">
                    <a className={"cursor-pointer nav-link " + (this.state.selected == 'properties' && 'active')} onClick={() => this.setState({selected: 'properties'})}>Properties</a>
                    {elements.length > 0 && <a className={"cursor-pointer nav-link " + (this.state.selected == 'elements' && 'active')} onClick={() => this.setState({selected: 'elements'})}>Elements</a>}
                </div>
            </div>
            <div className='col-10'>
                {this.state.selected == 'properties' ? <div className='d-flex flex-wrap flex-column'>
                    {Object.keys(event.properties).sort().map((key) =>
                        <div style={{flex: '0 1 '}} key={key}>
                            <strong>{key}:</strong>
                            {this.props.event.properties[key]}
                    </div>)}
                </div> : <this.ShowElements elements={elements} />}
            </div>
        </div>
    }
}

export class EventsTable extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            filters: fromParams(),
            newEvents: [],
            loading: true,
            highlightEvents: []
        }
        this.fetchEvents = this.fetchEvents.bind(this);
        this.FilterLink = this.FilterLink.bind(this);
        this.pollEvents = this.pollEvents.bind(this);
        this.clickNext = this.clickNext.bind(this);
        this.EventRow = this.EventRow.bind(this);
        this.clickLoadNewEvents = this.clickLoadNewEvents.bind(this);
        this.pollTimeout = 5000;
        this.fetchEvents();
    }
    fetchEvents() {
        let params = toParams({
            ...this.state.filters,
            ...this.props.fixedFilters
        })
        this.props.history.push({
            pathname: this.props.history.location.pathname,
            search: params
        });
        this.setState({loading: true});
        clearTimeout(this.poller)
        api.get('api/event/?' + params).then((events) => {
            this.setState({events: events.results, hasNext: events.next, loading: false});
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
            this.setState({newEvents: events.results, highlightEvents: []});
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
                let filters = {...this.state.filters}
                filters[props.property] = props.value;
                this.setState({filters}, this.fetchEvents);
                event.stopPropagation();
            }}
            >{typeof props.value === 'object' ? JSON.stringify(props.value) : props.value.replace(/(^\w+:|^)\/\//, '')}</Link>
    }
    clickNext() {
        let { events } = this.state;
        let params = toParams({
            ...this.state.filters,
            ...this.props.fixedFilters,
            before: events[events.length - 1].timestamp
        })
        this.setState({hasNext: false})
        api.get('api/event/?' + params).then((olderEvents) => {
            this.setState({events: [...events, ...olderEvents.results], hasNext: olderEvents.next, loading: false})
        });
    }
    clickLoadNewEvents() {
        let { newEvents, events } = this.state;
        this.setState({newEvents: [], events: [...newEvents, ...events], highlightEvents: newEvents.map((event) => event.id)})
    }
    EventRow(props) {
        let { event } = props;
        let { highlightEvents, eventSelected } = this.state;
        let params = ['$current_url', '$lib']
        return <tr key={event.id} className={'cursor-pointer event-row ' + (highlightEvents.indexOf(event.id) > -1 && 'event-row-new')} onClick={() => this.setState({eventSelected: eventSelected != event.id ? event.id : false})}>
            <td>
                {eventNameMap(event)}
                {event.elements.length > 0 && <pre style={{marginBottom: 0, display: 'inline'}}>&lt;{event.elements[0].tag_name}&gt;</pre>}
                {event.elements.length > 0 && event.elements[0].text && ' with text "' + event.elements[0].text + '"'}
            </td>
            <td><Link to={'/person/' + event.distinct_id}>{event.person}</Link></td>
            {params.map((param) => <td key={param} title={event.properties[param]}>
                <this.FilterLink property={param} value={event.properties[param]} />
            </td>)}
            <td>{moment(event.timestamp).fromNow()}</td>
        </tr>
    }
    NoItems(props) {
        if(!props.events || props.events.length > 0) return null;
        return <tr>
            <td colSpan="4">
                You don't have any items here. If you haven't integrated PostHog yet, <Link to='/setup'>click here to set PostHog up on your app</Link>
            </td>
        </tr>
    }
    render() {
        let { filters, events, loading, hasNext, newEvents, highlightEvents } = this.state;
        return (
            <div className='events'>
                <PropertyFilter propertyFilters={filters} onChange={(filters) => this.setState({filters}, this.fetchEvents)} history={this.props.history} />
                <table className='table' style={{position: 'relative'}}>
                    {loading && <div className='loading-overlay'><div></div></div>}
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
                        {loading && <div className='loading'><div></div></div>}
                        <tr
                            className={'event-new-events ' + (this.state.newEvents.length > 0 ? 'show' : 'hide')}
                            onClick={this.clickLoadNewEvents}>
                            <td colSpan="5"><div>There are {newEvents.length} new events. Click here to load them.</div></td>
                        </tr>
                        <this.NoItems events={events} />
                        {this.state.events && this.state.events.map((event, index) => [
                            index > 0 && !moment(event.timestamp).isSame(events[index - 1].timestamp, 'day') && <tr key={event.id + '_time'}><td colSpan="4" className='event-day-separator'>{moment(event.timestamp).format('LL')}</td></tr>,
                            <this.EventRow event={event} />,
                            this.state.eventSelected == event.id && <tr key={event.id + '_open'}>
                                <td colSpan="5">
                                    <EventDetails event={event} />
                                </td>
                            </tr>
                        ])}
                    </tbody>
                </table>
                {hasNext && <button className='btn btn-primary' onClick={this.clickNext} style={{margin: '2rem auto 15rem', display: 'block'}}>
                    Load more events
                </button>}
                <div style={{marginTop: '15rem'}}></div>
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
