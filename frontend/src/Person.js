import React, { Component } from 'react'
import { EventsTable } from './Events';
import api from './Api';

export default class Person extends Component {
    constructor(props) {
        super(props)
    
        this.state = {}
        this.fetchPerson.call(this);
    }
    fetchPerson() {
        api.get('api/person/by_distinct_id/?distinct_id=' + this.props.match.params.distinct_id).then((person) => this.setState({person}))
    }

    render() {
        return this.state.person ? <div>
                <h1>{this.state.person.name}</h1>
                <EventsTable fixedFilters={{person_id: this.state.person.id}} history={this.props.history} />
            </div>
        : null;
    }
}
