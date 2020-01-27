import React, { Component } from 'react';
import api from './Api';
import { EditAction } from '../editor/index';
import { EventsTable } from './Events';


export default class Action extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            newEvents: []
        }
    }
    render() {
        return <div>
            <EditAction actionId={this.props.match.params.id} />

            <h2>Events</h2>
            <EventsTable fixedFilters={{action_id: this.props.match.params.id}} history={this.props.history} />
        </div>
    }
}