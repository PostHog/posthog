import React, { Component } from 'react'
import api from '../../lib/api'
import { uuid } from '../../lib/utils'
import PropTypes from 'prop-types'
import { Link } from 'react-router-dom'
import { toast } from 'react-toastify'

import { ActionStep } from './ActionStep'

export class ActionEdit extends Component {
    constructor(props) {
        super(props)

        this.state = {
            action: { name: '', steps: [] },
            edited: false,
            focus: true,
            slackEnabled: props.user && props.user.team && props.user.team.slack_incoming_webhook,
        }
        this.params = '?include_count=1' + (props.temporaryToken ? '&temporary_token=' + props.temporaryToken : '')
        this.fetchAction.call(this)
        this.onSubmit = this.onSubmit.bind(this)
    }
    fetchAction() {
        if (this.props.actionId) {
            this.state.focus = false
            return api
                .get(this.props.apiURL + 'api/action/' + this.props.actionId + '/' + this.params)
                .then(action => this.setState({ action }))
        }
        // If it's a new action, add an empty step
        this.state.action = { name: '', steps: [{ isNew: uuid() }] }
    }
    onSubmit(event, createNew) {
        if (!event.target.form.checkValidity() || !this.state.edited) return
        let isNew = !this.state.action.id
        let save = action => {
            this.setState({
                error: false,
                saved: true,
                action: {
                    ...this.state.action,
                    id: action.id,
                    count: action.count,
                },
                edited: false,
            })
            if (this.props.onSave) this.props.onSave(action, isNew, createNew)
            toast('Action Saved', { autoClose: 3000, hideProgressBar: true })
        }
        let error = detail => {
            if (detail.detail == 'action-exists')
                this.setState({
                    saved: false,
                    error: 'action-exists',
                    error_id: detail.id,
                })
        }
        let steps = this.state.action.steps.map(step => {
            if (step.event == '$pageview') step.selection = ['url', 'url_matching']
            if (step.event != '$pageview' && step.event != '$autocapture') step.selection = []
            if (!step.selection) return step
            let data = {}
            Object.keys(step).map(key => {
                data[key] = key == 'id' || key == 'event' || step.selection.indexOf(key) > -1 ? step[key] : null
            })
            return data
        })
        if (this.state.action.id) {
            return api
                .update(this.props.apiURL + 'api/action/' + this.state.action.id + '/' + this.params, {
                    name: this.state.action.name,
                    post_to_slack: this.state.action.post_to_slack,
                    steps,
                })
                .then(save)
                .catch(error)
        }
        api.create(this.props.apiURL + 'api/action/' + this.params, {
            name: this.state.action.name,
            post_to_slack: this.state.action.post_to_slack,
            steps,
        })
            .then(save)
            .catch(error)
    }
    render() {
        let action = this.state.action
        let { isEditor, simmer } = this.props

        const addGroup = (
            <button
                type="button"
                className="btn btn-outline-success btn-sm"
                onClick={() => {
                    action.steps.push({ isNew: uuid() })
                    this.setState({ action: action })
                }}
            >
                Add another match group
            </button>
        )

        return (
            <div className={isEditor ? '' : 'card'} style={{ marginTop: isEditor ? 8 : '' }}>
                <form className={isEditor ? '' : 'card-body'} onSubmit={e => e.preventDefault()}>
                    <input
                        autoFocus={this.state.focus}
                        required
                        className="form-control"
                        placeholder="For example: user signed up"
                        value={action.name}
                        onChange={e =>
                            this.setState({
                                action: { ...action, name: e.target.value },
                                edited: e.target.value ? true : false,
                            })
                        }
                    />

                    {action.count > -1 && (
                        <div>
                            <small className="text-muted">Matches {action.count} events</small>
                        </div>
                    )}

                    {!isEditor && <br />}

                    {action.steps.map((step, index) => (
                        <>
                            {index > 0 ? (
                                <div
                                    style={{
                                        textAlign: 'center',
                                        fontSize: 13,
                                        letterSpacing: 1,
                                        opacity: 0.7,
                                        margin: 8,
                                    }}
                                >
                                    OR
                                </div>
                            ) : null}
                            <ActionStep
                                key={step.id || step.isNew}
                                step={step}
                                isEditor={isEditor}
                                actionId={action.id}
                                simmer={simmer}
                                onDelete={() => {
                                    action.steps = action.steps.filter(s => s.id != step.id)
                                    this.setState({ action: action })
                                }}
                                onChange={newStep => {
                                    action.steps = action.steps.map(s =>
                                        (step.id && s.id == step.id) || (step.isNew && s.isNew === step.isNew)
                                            ? {
                                                  id: step.id,
                                                  isNew: step.isNew,
                                                  ...newStep,
                                              }
                                            : s
                                    )
                                    this.setState({ action: action, edited: true })
                                }}
                            />
                        </>
                    ))}

                    {!isEditor ? (
                        <div style={{ marginTop: 20, marginBottom: 15 }}>
                            <label className={this.state.slackEnabled ? '' : 'disabled'} style={{ marginRight: 5 }}>
                                <input
                                    type="checkbox"
                                    onChange={e => {
                                        this.setState({ action: { ...action, post_to_slack: e.target.checked } })
                                    }}
                                    checked={action.post_to_slack}
                                    disabled={!this.state.slackEnabled}
                                />
                                &nbsp;Post to Slack when this action is triggered.
                            </label>
                            <Link to="/setup#slack">
                                <small>Configure</small>
                            </Link>
                        </div>
                    ) : (
                        <br />
                    )}

                    {this.state.error && (
                        <p className="text-danger">
                            Action with this name already exists.{' '}
                            <a href={this.props.apiURL + 'action/' + this.state.error_id}>Click here to edit.</a>
                        </p>
                    )}

                    {isEditor ? <div style={{ marginBottom: 20 }}>{addGroup}</div> : null}

                    <div className={isEditor ? 'btn-group save-buttons' : ''}>
                        {!isEditor ? addGroup : null}
                        <button
                            type="submit"
                            disabled={!this.state.edited}
                            onClick={e => this.onSubmit(e)}
                            className={
                                this.state.edited
                                    ? 'btn-success btn btn-sm float-right'
                                    : 'btn-secondary btn btn-sm float-right'
                            }
                        >
                            Save action
                        </button>

                        {this.props.isEditor && this.props.showNewActionButton && (
                            <button
                                type="submit"
                                onClick={e => this.onSubmit(e, true)}
                                className="btn btn-secondary btn-sm float-right"
                            >
                                Save & new action
                            </button>
                        )}
                    </div>
                </form>
            </div>
        )
    }
}
ActionEdit.propTypes = {
    isEditor: PropTypes.bool,
    simmer: PropTypes.func,
    onSave: PropTypes.func,
}
