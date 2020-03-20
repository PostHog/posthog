import React, { Component } from 'react'
import { EventsTable } from '../events/EventsTable'
import api from '../../lib/api'
import { PropertiesTable } from '../../lib/components/PropertiesTable'
import { toast } from 'react-toastify'

export class Person extends Component {
    constructor(props) {
        super(props)

        this.state = {}
        this.fetchPerson.call(this)
    }
    fetchPerson() {
        let url = ''
        if (this.props.match.params.distinct_id) {
            url =
                'api/person/by_distinct_id/?distinct_id=' +
                this.props.match.params.distinct_id
        } else {
            url = 'api/person/' + this.props.match.params.id
        }
        api.get(url).then(person => this.setState({ person }))
    }

    render() {
        return this.state.person ? (
            <div>
                <button
                    className="btn btn-outline-danger btn-sm float-right"
                    onClick={e =>
                        confirm(
                            'Are you sure you want to delete this user? This cannot be undone'
                        ) &&
                        api
                            .delete('api/person/' + this.state.person.id)
                            .then(() => {
                                toast('Person succesfully deleted.')
                                this.props.history.push('/people')
                            })
                    }
                >
                    Delete all data on this person
                </button>
                <h1>{this.state.person.name}</h1>
                <div style={{ maxWidth: 750 }}>
                    <PropertiesTable properties={this.state.person.properties} />
                    <table className="table">
                        <tbody>
                            <tr>
                                <td>Distinct IDs</td>
                                <td>
                                    {this.state.person.distinct_ids.map(
                                        distinct_id => (
                                            <pre style={{ margin: 0 }}>
                                                {distinct_id}
                                            </pre>
                                        )
                                    )}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <EventsTable
                    fixedFilters={{ person_id: this.state.person.id }}
                    history={this.props.history}
                />
            </div>
        ) : null
    }
}
