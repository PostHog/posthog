import React, { Component } from 'react'
import api from './Api';
import { Link } from 'react-router-dom';
import moment from 'moment';

export default class People extends Component {
    constructor(props) {
        super(props)
    
        this.state = {}
        this.fetchPeople.call(this);
    }
    fetchPeople() {
        api.get('api/person').then((data) => this.setState({people: data.results}))
    }
    render() {
        return (
            <div>
                <table className='table'>
                    <tr><th>Person</th><th>Last seen</th></tr>
                    {this.state.people && this.state.people.map((person) => <tr key={person.id}>
                        <td><Link to={'/person/' + person.distinct_ids[0]}>{person.name}</Link></td>
                        <td>{person.last_event && moment(person.last_event.timestamp).fromNow()}</td>
                    </tr>)}
                </table>
            </div>
        )
    }
}
