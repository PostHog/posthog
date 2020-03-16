import React, { Component } from 'react'
import { Card, uuid, Loading } from '../../lib/utils'
import api from '../../lib/api'
import { toast } from 'react-toastify'
import { Link } from 'react-router-dom'
import PropTypes from 'prop-types'
import { ActionSelectBox } from '../../lib/components/ActionSelectBox'

export class EditFunnel extends Component {
    constructor(props) {
        super(props)

        this.state = {
            actions: false,
            id: props.funnelId,
            steps: props.funnelId ? false : [{ id: uuid(), order: 0 }]
        }
        this.Step = this.Step.bind(this)
        this.onSubmit = this.onSubmit.bind(this)
        this.fetchActions.call(this)
        if (this.state.id) this.fetchFunnel.call(this)
    }
    fetchFunnel() {
        api.get('api/funnel/' + this.state.id + '/?exclude_count=1').then(funnel =>
            this.setState({
                steps:
                    funnel.steps.length > 0
                        ? funnel.steps
                        : [{ id: uuid(), order: 0 }],
                name: funnel.name,
            })
        )
    }
    fetchActions() {
        api.get('api/action').then(actions =>
            this.setState({ actions: actions.results })
        )
    }
    Step(step) {
        let { steps, actions } = this.state
        let selectedAction =
            actions && actions.filter(action => action.id == step.action_id)[0]
        return (
            <Card style={{ marginBottom: '1rem' }}>
                <div className="funnel-step-side">
                    {step.index + 1}
                    <br />
                    <button
                        type="button"
                        className="close float-right"
                        onClick={() =>
                            this.setState({
                                steps: steps.filter(
                                    s => s.id != step.id
                                ),
                            })
                        }
                    >
                        <span style={{ display: 'block' }}>×</span>
                    </button>
                </div>
                <div className="card-body">
                    {actions && <ActionSelectBox
                        onChange={action_id => {
                            this.setState(
                                {
                                    steps: this.state.steps.map(s =>
                                        s.id == step.id
                                            ? {
                                                    ...step,
                                                    action_id,
                                                }
                                            : s
                                    ),
                                }
                            )
                        }}
                        actions={actions}
                        action={selectedAction || {}}
                    />}
                </div>
            </Card>
        )
    }
    onSubmit(event) {
        if (event) event.preventDefault()
        let save = funnel => {
            toast('Funnel saved.', { autoClose: 3000, hideProgressBar: true })
            this.props.onChange && this.props.onChange(funnel)
        }
        let data = {
            name: this.state.name,
            id: this.state.id,
            steps: this.state.steps,
        }
        if (this.state.id) {
            return api.update('api/funnel/' + this.state.id, data).then(save)
        }
        api.create('api/funnel', data).then(funnel =>
            this.props.history.push('/funnel/' + funnel.id)
        )
    }
    render() {
        let { dndLoaded, name, steps, actions } = this.state;
        return (
            <form onSubmit={this.onSubmit}>
                <Card>
                    {steps ? <div className="card-body">
                        <label>Name</label>
                        <input
                            required
                            placeholder="User drop off through signup"
                            type="text"
                            autoFocus
                            onChange={e =>
                                this.setState({ name: e.target.value })
                            }
                            value={name}
                            className="form-control"
                        />
                        {actions && actions.length == 0 && (
                            <div
                                className="alert alert-warning"
                                style={{ marginTop: '1rem' }}
                            >
                                You don't have any actions set up.{' '}
                                <Link to="/actions">
                                    Click here to set up an action
                                </Link>
                            </div>
                        )}
                        <br />
                        <div>
                            {this.state.steps.map(
                                (step, index) => (<div className='funnel-step'>
                                    <this.Step
                                        key={step.id}
                                        index={index}
                                        {...step}
                                    />
                                </div>)
                            )}
                        </div>
                        <div className="btn-group">
                            <button
                                className="btn btn-outline-secondary btn-sm"
                                type="button"
                                onClick={() =>
                                    this.setState({
                                        steps: [
                                            ...steps,
                                            { id: uuid(), order: steps.length },
                                        ],
                                    })
                                }
                            >
                                Add step
                            </button>
                            <button
                                className="btn btn-success btn-sm"
                                type="submit"
                            >
                                Save funnel
                            </button>
                        </div>
                    </div> : <Loading />}
                </Card>
                {this.state.saved && (
                    <p className="text-success">
                        Funnel saved.{' '}
                        <Link to={'/funnel/' + this.state.id}>
                            Click here to go back to the funnel.
                        </Link>
                    </p>
                )}
            </form>
        )
    }
}

EditFunnel.propTypes = {
    history: PropTypes.object,
    funnel: PropTypes.object,
}
