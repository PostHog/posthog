import React, { Component } from 'react';
import api from './Api';
import moment from 'moment';
import { Link } from 'react-router-dom';

let toParams = (obj) => Object.entries(obj).map(([key, val]) => `${key}=${encodeURIComponent(val)}`).join('&')
let fromParams = () => window.location.search != '' && window.location.search.slice(1).split('&').reduce((a, b) => { b = b.split('='); a[b[0]] = decodeURIComponent(b[1]); return a; }, {});
let colors = ['success', 'secondary', 'warning', 'primary', 'danger', 'info', 'dark', 'light']

export default class Events extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            filters: fromParams()
        }
        this.fetchEvents = this.fetchEvents.bind(this);
        this.FilterLink = this.FilterLink.bind(this);
        this.Filters = this.Filters.bind(this);
        this.fetchEvents();
    }
    fetchEvents() {
        api.get('api/event/?' + toParams(this.state.filters)).then((events) => this.setState({events: events.results}))
    }
    FilterLink(props) {
        let filters = {...this.state.filters};
        filters[props.property] = props.value;
        return <Link
            to={'/events/?' + toParams(filters)}
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
                    this.props.history.push('/events/?' + toParams(this.state.filters))
                }}>
                    <span aria-hidden="true">&times;</span>
                </button>
            </div>)}
        </div>
    }
    render() {
        let params = ['distinct_id', '$current_url']
        return (
            <div class='events'>
                <this.Filters />
                <table className='table'>
                    <tbody>
                        <tr><th>Event</th><th>Person</th><th>Path</th><th>When</th></tr>
                        {this.state.events && this.state.events.map((event) => [<tr key={event.id} className='cursor-pointer event-row' onClick={() => this.setState({eventSelected: this.state.eventSelected != event.id ? event.id : false})}>
                            <td>
                                {event.properties.$event_type == 'click' ? 'clicked' : event.event}
                                {event.elements && ' a ' + event.elements[0].tag_name + ' element '}
                                {event.elements[0].$el_text && ' with text ' + event.elements[0].$el_text}
                            </td>
                            {params.map((param) => <td key={param} title={event.properties[param]}>
                                <this.FilterLink property={param} value={event.properties[param]} />
                            </td>)}
                            <td>{moment(event.timestamp).fromNow()}</td>
                            {/* <td><pre>{JSON.stringify(event)}</pre></td> */}
                        </tr>,
                        this.state.eventSelected == event.id && <tr>
                            <td colSpan="4">
                                <div className='d-flex flex-wrap'>
                                    {Object.keys(event.properties).map((key) => <div style={{width: '25%'}} key={key}>
                                        <strong>{key}:</strong> <this.FilterLink property={key} value={event.properties[key]} />
                                    </div>)}
                                </div>
                            </td>
                        </tr>
                        ])}
                    </tbody>
                </table>
            </div>
        )
    }
}
