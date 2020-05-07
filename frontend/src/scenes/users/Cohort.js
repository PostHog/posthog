import React, { Component } from 'react'
import { Card, CloseButton, fromParams } from 'lib/utils'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { CohortGroup } from './CohortGroup'
import { router } from 'kea-router'

export class _Cohort extends Component {
    constructor(props) {
        super(props)
        this.state = {
            groups: window.location.search.indexOf('new_cohort') > -1 ? [{}] : [],
            id: fromParams()['cohort'],
            name: '',
        }
        this.fetchProperties.call(this)
        this.fetchActions.call(this)
        this.onSave = this.onSave.bind(this)
        if (this.state.id) this.fetchCohort.call(this)
    }
    fetchCohort() {
        api.get('api/cohort/' + this.state.id).then(cohort => this.setState(cohort))
    }
    onSave(e) {
        e.preventDefault()
        let cohort = {
            id: this.state.id,
            name: this.state.name,
            groups: this.state.groups,
        }
        let onResponse = cohort => {
            this.props.onChange(cohort.id)
            this.setState({ id: cohort.id })
            toast('Cohort saved.')
            this.actions.push(this.props.location.pathname, { cohort: cohort.id })
        }
        if (this.state.id) {
            return api.update('api/cohort/' + this.state.id, cohort).then(onResponse)
        }
        api.create('api/cohort', cohort).then(onResponse)
    }
    fetchProperties() {
        api.get('api/person/properties').then(properties => {
            this.setState({
                properties: properties.map(property => ({
                    label: property.name,
                    value: property.name,
                })),
            })
        })
    }
    fetchActions() {
        api.get('api/action').then(actions => {
            this.setState({
                actions: actions.results.map(action => ({
                    label: action.name,
                    value: action.id,
                })),
            })
        })
    }
    render() {
        let { groups, properties, actions, name } = this.state
        return groups.length === 0 ? (
            <button
                className="btn btn-sm btn-outline-success float-right"
                style={{ marginBottom: '1rem', marginLeft: 12 }}
                onClick={() => this.setState({ groups: [{}] })}
            >
                + new cohort
            </button>
        ) : (
            <div style={{ maxWidth: 750 }}>
                <Card
                    title={
                        <span>
                            <CloseButton
                                className="float-right"
                                onClick={() => {
                                    this.setState({ groups: [], id: false })
                                    this.props.onChange()
                                    this.actions.push(`${this.props.location.pathname}`)
                                }}
                            />
                            {name || 'New cohort'}
                        </span>
                    }
                >
                    <form className="card-body" onSubmit={this.onSave}>
                        <input
                            style={{ marginBottom: '1rem' }}
                            required
                            className="form-control"
                            autoFocus
                            placeholder="Cohort name..."
                            value={name}
                            onChange={e => this.setState({ name: e.target.value })}
                        />
                        {groups
                            .map((group, index) => (
                                <CohortGroup
                                    key={index}
                                    group={group}
                                    properties={properties}
                                    actions={actions}
                                    index={index}
                                    onRemove={() => {
                                        groups.splice(index, 1)
                                        this.setState({ groups })
                                    }}
                                    onChange={group => {
                                        groups[index] = group
                                        this.setState({ groups })
                                    }}
                                />
                            ))
                            .reduce((prev, curr) => [
                                prev,
                                <div className="secondary" style={{ textAlign: 'center', margin: 8 }}>
                                    {' '}
                                    OR{' '}
                                </div>,
                                curr,
                            ])}
                        <button
                            className="btn btn-outline-success btn-sm"
                            style={{ marginTop: '1rem' }}
                            type="button"
                            onClick={() => this.setState({ groups: [...groups, {}] })}
                        >
                            New group
                        </button>
                        <button className="btn btn-success btn-sm float-right" style={{ marginTop: '1rem' }}>
                            Save cohort
                        </button>
                    </form>
                </Card>
            </div>
        )
    }
}

export const Cohort = router(_Cohort)
