import React, { Component } from 'react'
import { Link } from 'react-router-dom';
import { DeleteWithUndo, Loading } from './utils';
import api from "./Api";

export default class Cohorts extends Component {
    constructor(props) {
        super(props)
    
        this.state = {
            loading: true
        }
        this.fetchCohorts = this.fetchCohorts.bind(this);
        this.fetchCohorts();
    }
    fetchCohorts() {
        api.get('api/cohort').then(cohorts => this.setState({cohorts: cohorts.results, loading: false}))
    }
    render() {
        let { cohorts, loading } = this.state;
        return (
            <div>
                <h1>Cohorts</h1>
                <Link to={'/people?new_cohort='} className='btn btn-outline-success btn-sm'>+ new cohort</Link>
                <br /><br />
                <table className='table' style={{position: 'relative'}}>
                    {loading && <Loading />}
                    <tbody>
                        <tr><th>Cohort name</th><th>Actions</th></tr>
                        {cohorts && cohorts.map(cohort => <tr key={cohort.id}>
                            <td><Link to={'/people?cohort=' + cohort.id}>{cohort.name}</Link></td>
                            <td>
                                <DeleteWithUndo
                                    endpoint="cohort"
                                    object={cohort}
                                    className='text-danger'
                                    style={{marginLeft: 8}}
                                    callback={this.fetchCohorts}>
                                    <i className='fi flaticon-basket' />
                                </DeleteWithUndo>
                            </td>
                        </tr>)}
                    </tbody>
                </table>
            </div>
        )
    }
}
