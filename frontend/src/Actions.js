import React, { Component } from 'react';
import api from './Api';
import { Link } from 'react-router-dom';
import { appEditorUrl } from './utils';


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
            <div>
                <a href={appEditorUrl(this.props.user.team)} target="_blank" className='btn btn-outline-success float-right'><i className='fi flaticon-add'/>&nbsp;&nbsp;New action&nbsp;<i className='fi flaticon-export' /></a>
                <h1>Actions</h1>
                <table className='table'>
                    <thead>
                        <tr>
                            <th scope="col">Action ID</th>
                            <th scope="col">Type</th>
                            <th scope="col">User</th>
                            <th scope="col">Date</th>
                            <th scope="col">Browser</th>
                            <th scope="col">City</th>
                            <th scope="col">Country</th>
                        </tr>
                    </thead>
                    <tbody>
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
    constructor(props) {
        super(props)
    }
    render() {
        return <ActionsTable {...this.props} />
    }
}
