import React, { Component } from 'react'
import api from '../../lib/api'
import { uuid } from '../../lib/utils'
import PropTypes from 'prop-types'
import { ActionStep } from './ActionStep'

export class ActionEdit extends Component {
    constructor(props) {
        super(props)

        this.state = {
            action: { name: '', steps: [] },
        }
        this.params =
            '?include_count=1' +
            (props.temporaryToken
                ? '&temporary_token=' + props.temporaryToken
                : '')
        this.fetchAction.call(this)
        this.onSubmit = this.onSubmit.bind(this)
    }
    fetchAction() {
        if (this.props.actionId) {
            return api
                .get(
                    this.props.apiURL +
                        'api/action/' +
                        this.props.actionId +
                        '/' +
                        this.params
                )
                .then(action => this.setState({ action }))
        }
        // If it's a new action, add an empty step
        this.state.action = { name: '', steps: [{ isNew: uuid() }] }
    }
    onSubmit(event, createNew) {
        if (!event.target.form.checkValidity()) return
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
            })
            if (this.props.onSave) this.props.onSave(action, isNew, createNew)
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
            if (step.event == '$pageview')
                step.selection = ['url', 'url_matching']
            if (step.event != '$pageview' && step.event != '$autocapture')
                step.selection = []
            if (!step.selection) return step
            let data = {}
            Object.keys(step).map(key => {
                data[key] =
                    key == 'id' ||
                    key == 'event' ||
                    step.selection.indexOf(key) > -1
                        ? step[key]
                        : null
            })
            return data
        })
        if (this.state.action.id) {
            return api
                .update(
                    this.props.apiURL +
                        'api/action/' +
                        this.state.action.id +
                        '/' +
                        this.params,
                    { name: this.state.action.name, steps }
                )
                .then(save)
                .catch(error)
        }
        api.create(this.props.apiURL + 'api/action/' + this.params, {
            name: this.state.action.name,
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
            <div
                className={isEditor ? '' : 'card'}
                style={{ marginTop: isEditor ? 8 : '' }}
            >
                <form
                    className={isEditor ? '' : 'card-body'}
                    onSubmit={e => e.preventDefault()}
                >
                    <input
                        autoFocus
                        required
                        className="form-control"
                        placeholder="For example: user signed up"
                        value={action.name}
                        onChange={e =>
                            this.setState({
                                action: { ...action, name: e.target.value },
                            })
                        }
                    />

                    {action.count > -1 && (
                        <div>
                            <small className="text-muted">
                                Matches {action.count} events
                            </small>
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
                                    action.steps = action.steps.filter(
                                        s => s.id != step.id
                                    )
                                    this.setState({ action: action })
                                }}
                                onChange={newStep => {
                                    action.steps = action.steps.map(s =>
                                        (step.id && s.id == step.id) ||
                                        (step.isNew && s.isNew === step.isNew)
                                            ? {
                                                  id: step.id,
                                                  isNew: step.isNew,
                                                  ...newStep,
                                              }
                                            : s
                                    )
                                    this.setState({ action: action })
                                }}
                            />
                        </>
                    ))}

                    <br />

                    {this.state.saved && !isEditor && (
                        <p className="text-success">Action saved.</p>
                    )}

                    {this.state.error && (
                        <p className="text-danger">
                            Action with this name already exists.{' '}
                            <a
                                href={
                                    this.props.apiURL +
                                    'action/' +
                                    this.state.error_id
                                }
                            >
                                Click here to edit.
                            </a>
                        </p>
                    )}

                    {isEditor ? (
                        <div style={{ marginBottom: 20 }}>{addGroup}</div>
                    ) : null}

                    <div className={isEditor ? 'btn-group save-buttons' : ''}>
                        {!isEditor ? addGroup : null}
                        <button
                            type="submit"
                            onClick={e => this.onSubmit(e)}
                            className="btn btn-success btn-sm float-right"
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
