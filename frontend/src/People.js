import React, { Component } from 'react'
import api from './Api';
import { Link } from 'react-router-dom';
import moment from 'moment';

let toParams = (obj) => Object.entries(obj).map(([key, val]) => `${key}=${encodeURIComponent(val)}`).join('&')
export default class People extends Component {
    constructor(props) {
        super(props)
    
        this.state = {}
        this.FilterLink = this.FilterLink.bind(this);
        this.fetchPeople.call(this);
    }
    fetchPeople() {
        api.get('api/person/?include_last_event=1').then((data) => this.setState({people: data.results}))
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
    render() {
        return (
            <div>
                <h1>Users</h1>
                <table className='table'>
                    <tbody>
                        <tr><th>Person</th><th>Last seen</th></tr>
                        {this.state.people && this.state.people.length == 0 && <tr><td colSpan="2">We haven't seen any data yet. If you haven't integrated PostHog, <Link to='/setup'>click here to set PostHog up on your app</Link></td></tr>}
                        {this.state.people && this.state.people.map((person) => [
                            <tr key={person.id} className='cursor-pointer' onClick={() => this.setState({personSelected: person.id})}>
                                <td><Link to={'/person/' + person.distinct_ids[0]}>{person.name}</Link></td>
                                <td>{person.last_event && moment(person.last_event.timestamp).fromNow()}</td>
                            </tr>,
                            this.state.personSelected == person.id && <tr key={person.id + '_open'}>
                                <td colSpan="4">
                                    <div className='d-flex flex-wrap flex-column' style={{height: 200}}>
                                        {Object.keys(person.properties).sort().map((key) => <div style={{flex: '0 1 '}} key={key}>
                                            <strong>{key}:</strong> <this.FilterLink property={key} value={person.properties[key]} />
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
