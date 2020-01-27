import React, { Component } from 'react';
import api from './Api';
import { Link } from 'react-router-dom';


export class ActionsTable extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            newEvents: []
        }
        this.fetchEvents = this.fetchEvents.bind(this);
        this.fetchEvents();
    }
    fetchEvents() {
        clearTimeout(this.poller)
        api.get('api/action').then((actions) => {
            this.setState({actions: actions.results});
        })
    }
    
    render() {
        return (
            <div class='events'>
                <table className='table'>
                    <tbody>
                        <tr><th>Name</th><th>Matching events</th></tr>
                        {this.state.actions && this.state.actions.map((action) => 
                            <tr key={action.id}>
                                <td>
                                    <Link to={'/action/' + action.id}>{action.name}</Link>
                                </td>
                                <td>{action.count}</td>
                                {/* <td>{moment(event.timestamp).fromNow()}</td> */}
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        )
    }
}

export default class Actions extends Component {
    render() {
        return <ActionsTable {...this.props} />
    }
}
