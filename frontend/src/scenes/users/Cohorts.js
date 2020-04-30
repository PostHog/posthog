import React, { Component } from 'react'
import { Link } from 'react-router-dom'
import { DeleteWithUndo, Loading } from '../../lib/utils'
import { Tooltip } from 'antd'
import { ExportOutlined, DeleteOutlined } from '@ant-design/icons'
import api from '../../lib/api'

export class Cohorts extends Component {
    constructor(props) {
        super(props)

        this.state = {
            loading: true,
        }
        this.fetchCohorts = this.fetchCohorts.bind(this)
        this.fetchCohorts()
    }
    fetchCohorts() {
        api.get('api/cohort').then(cohorts => this.setState({ cohorts: cohorts.results, loading: false }))
    }
    render() {
        let { cohorts, loading } = this.state
        return (
            <div>
                <h1>Cohorts</h1>
                <Link to={'/people?new_cohort='} className="btn btn-outline-success btn-sm">
                    + new cohort
                </Link>
                <br />
                <br />
                <table className="table" style={{ position: 'relative' }}>
                    {loading && <Loading />}
                    <tbody>
                        <tr>
                            <th>Cohort name</th>
                            <th>Actions</th>
                        </tr>
                        {cohorts &&
                            cohorts.map(cohort => (
                                <tr key={cohort.id}>
                                    <td>
                                        <Link to={'/people?cohort=' + cohort.id}>{cohort.name}</Link>
                                    </td>
                                    <td>
                                        <a href={'/api/person.csv?cohort=' + cohort.id}>
                                            <Tooltip title="Export all users in this cohort as a .csv file">
                                                <ExportOutlined />
                                            </Tooltip>
                                        </a>
                                        <DeleteWithUndo
                                            endpoint="cohort"
                                            object={cohort}
                                            className="text-danger"
                                            style={{ marginLeft: 8 }}
                                            callback={this.fetchCohorts}
                                        >
                                            <DeleteOutlined />
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
