import React, { Component } from 'react';
import { EventsTable } from './Events';
import { ActionEdit } from './ActionEdit';


export default class Action extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            newEvents: []
        }
    }
    render() {
        return <div>
            <h1>{this.props.match.params.id ? 'Edit action' : 'New action'}</h1>
            <ActionEdit apiURL='' user={this.props.user} actionId={this.props.match.params.id} />
            {this.props.match.params.id && <div>
                <hr />

                <h2>Events</h2>
                <EventsTable fixedFilters={{action_id: this.props.match.params.id}} history={this.props.history} />
            </div>}
        </div>
    }
}