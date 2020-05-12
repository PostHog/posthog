import React, { Component } from 'react'
import { Link } from 'lib/components/Link'
import api from 'lib/api'
import { DeleteWithUndo, TableRowLoading } from 'lib/utils'

export class Funnels extends Component {
    constructor(props) {
        super(props)

        this.state = { loading: true, funnels: [] }
        this.fetchFunnels = this.fetchFunnels.bind(this)
        this.fetchFunnels()
    }
    fetchFunnels() {
        api.get('api/funnel').then(funnels => {
            this.setState({ funnels: funnels.results, loading: false })
        })
    }
    render() {
        return (
            <div>
                <Link to="/funnel/new" className="btn btn-outline-success float-right">
                    <i className="fi flaticon-add" />
                    &nbsp;&nbsp;New funnel
                </Link>
                <h1>Funnels</h1>
                <p style={{ maxWidth: 600 }}>
                    <i>
                        If you need your users to carry out a series of actions in a row, funnels are a way of working
                        out where users are dropping off.{' '}
                        <a href="https://docs.posthog.com/#/features/funnels" target="_blank" rel="noopener noreferrer">
                            See documentation
                        </a>
                    </i>
                </p>
                <table className="table">
                    <thead>
                        <tr>
                            <th>Funnel name</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {this.state.loading && (
                            <TableRowLoading colSpan={2} asOverlay={this.state.funnels.length > 0} />
                        )}
                        {this.state.funnels && this.state.funnels.length === 0 && (
                            <tr>
                                <td colSpan="6">
                                    You haven't created any funnels yet.{' '}
                                    <Link to="/funnel/new">Click here to create one!</Link>
                                </td>
                            </tr>
                        )}
                        {this.state.funnels &&
                            this.state.funnels.map(funnel => (
                                <tr key={funnel.id}>
                                    <td>
                                        <Link to={`/funnel/${funnel.id}`}>{funnel.name}</Link>
                                    </td>
                                    <td style={{ fontSize: 16 }}>
                                        <Link to={`/funnel/${funnel.id}`}>
                                            <i className="fi flaticon-edit" />
                                        </Link>
                                        <DeleteWithUndo
                                            endpoint="funnel"
                                            object={funnel}
                                            className="text-danger"
                                            style={{ marginLeft: 8 }}
                                            callback={this.fetchFunnels}
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
