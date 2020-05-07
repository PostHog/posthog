import React, { Component } from 'react'
import api from 'lib/api'
import { Link } from 'lib/components/Link'
import { DeleteWithUndo, TableRowLoading } from 'lib/utils'

export class ActionsTable extends Component {
    constructor(props) {
        super(props)

        this.state = {
            actions: [],
            newEvents: [],
            loading: true,
        }
        this.fetchActions = this.fetchActions.bind(this)
        this.fetchActions()
    }
    fetchActions() {
        clearTimeout(this.poller)
        if (!this.state.loading) this.setState({ loading: true })
        api.get('api/action/?include_count=1').then(actions => {
            this.setState({ actions: actions.results, loading: false })
        })
    }

    render() {
        let { actions, loading } = this.state
        return (
            <div>
                <div className="btn-group float-right">
                    <Link to="/action" className="btn btn-success">
                        <i className="fi flaticon-add" />
                        &nbsp; New action
                    </Link>
                </div>
                <h1>Actions</h1>
                <p style={{ maxWidth: 600 }}>
                    <i>
                        Actions are PostHog’s way of easily cleaning up a large amount of Event data. Actions consist of
                        one or more events that you have decided to put into a manually-labelled bucket. They're used in
                        Funnels, Live actions and Trends.
                        <br />
                        <br />
                        <a href="https://github.com/PostHog/posthog/wiki/Actions" target="_blank">
                            See documentation
                        </a>
                    </i>
                </p>

                <table className="table" style={{ position: 'relative' }}>
                    <thead>
                        <tr>
                            <th scope="col">Action ID</th>
                            <th scope="col">Volume</th>
                            <th scope="col">Type</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && <TableRowLoading colSpan={4} asOverlay={actions.length > 0} />}
                        {actions && actions.length === 0 && (
                            <tr>
                                <td>You don't have any actions yet.</td>
                            </tr>
                        )}
                        {actions &&
                            actions.map(action => (
                                <tr key={action.id}>
                                    <td>
                                        <Link to={'/action/' + action.id}>{action.name}</Link>
                                    </td>
                                    <td>{action.count}</td>
                                    <td>
                                        {action.steps.map(step => (
                                            <div key={step.id}>
                                                {(() => {
                                                    switch (step.event) {
                                                        case '$autocapture':
                                                            return 'Autocapture'
                                                        case '$pageview':
                                                            return 'URL matches ' + step.url
                                                        default:
                                                            return 'Event: ' + step.event
                                                    }
                                                })()}
                                            </div>
                                        ))}
                                    </td>
                                    <td style={{ fontSize: 16 }}>
                                        <Link to={'/action/' + action.id}>
                                            <i className="fi flaticon-edit" />
                                        </Link>
                                        <DeleteWithUndo
                                            endpoint="action"
                                            object={action}
                                            className="text-danger"
                                            style={{ marginLeft: 8 }}
                                            callback={this.fetchActions}
                                        >
                                            <i className="fi flaticon-basket" />
                                        </DeleteWithUndo>
                                    </td>
                                </tr>
                            ))}
                    </tbody>
                </table>
            </div>
        )
    }
}
