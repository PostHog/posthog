import React, { Component } from 'react';
import api from './Api';
import { Link } from 'react-router-dom';
import { DeleteWithUndo } from './utils';
import { AppEditorLink } from './AppEditorLink'

export class ActionsTable extends Component {
    constructor(props) {
        super(props)

        this.state = {
            newEvents: [],
            loading: true
        }
        this.fetchActions = this.fetchActions.bind(this);
        this.fetchActions();
    }
    fetchActions() {
        clearTimeout(this.poller)
        if(!this.state.loading) this.setState({loading: true});
        api.get('api/action/?include_count=1').then((actions) => {
            this.setState({actions: actions.results, loading: false});
        })
    }

    render() {
        let { actions, loading } = this.state;
        return (
            <div>
                <div className='btn-group float-right'>
                    <Link to='/action' className='btn btn-light'><i className='fi flaticon-add'/>&nbsp; New action</Link>
                    <AppEditorLink onUpdateUser={this.props.onUpdateUser} user={this.props.user} className='btn btn-success'><i className='fi flaticon-export' /></AppEditorLink>
                </div>
                <h1>Actions</h1>
                <p style={{maxWidth: 600}}><i>
                    Actions are PostHog’s way of easily cleaning up a large amount of Event data.
                    Actions consist of one or more events that you have decided to put into a manually-labelled bucket. They're used in Funnels, Live actions and Trends.<br /><br />
                    <a href='https://github.com/PostHog/posthog/wiki/Actions' target="_blank">See documentation</a>
                </i></p>

                <table className='table' style={{position: 'relative'}}>
                    {loading && <div className='loading-overlay'><div></div></div>}
                    <thead>
                        <tr>
                            <th scope="col">Action ID</th>
                            <th scope="col">Volume</th>
                            <th scope="col">Type</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {actions && actions.length == 0 && <tr><td>You don't have any actions yet.</td></tr>}
                        {actions && actions.map((action) =>
                            <tr key={action.id}>
                                <td>
                                    <Link to={'/action/' + action.id}>{action.name}</Link>
                                </td>
                                <td>{action.count}</td>
                                <td>{action.steps.map((step) =>
                                    <div key={step.id}>
                                        {(() => {
                                            switch (step.event) {
                                                case '$autocapture':    return 'Autocapture';
                                                case '$pageview':       return 'URL matches ' + step.url;
                                                default:                return 'Event: ' + step.event
                                            }
                                        })()}
                                    </div>)}
                                </td>
                                <td style={{fontSize: 16}}>
                                    <Link to={'/action/' + action.id}><i className='fi flaticon-edit' /></Link>
                                    <DeleteWithUndo
                                        endpoint="action"
                                        object={action}
                                        className='text-danger'
                                        style={{marginLeft: 8}}
                                        callback={this.fetchActions}>
                                        <i className='fi flaticon-basket' />
                                    </DeleteWithUndo>
                                </td>
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
