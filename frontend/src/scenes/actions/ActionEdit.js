import React, { useState, Fragment } from 'react'
import { uuid, Loading } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { useValues, useActions } from 'kea'
import { actionEditLogic } from './actionEditLogic'
import { onboardingLogic } from '~/layout/onboarding'
import { ActionStep } from './ActionStep'

export function ActionEdit({ actionId, apiURL, onSave, user, isEditor, simmer, showNewActionButton, temporaryToken }) {
    let logic = actionEditLogic({
        id: actionId,
        apiURL,
        onSave: (action, createNew) => onSave(action, !actionId, createNew),
        temporaryToken,
    })
    const { action, actionLoading, errorActionId } = useValues(logic)
    const { setAction, saveAction, setCreateNew } = useActions(logic)
    const { updateOnboardingStep } = useActions(onboardingLogic)
    const [edited, setEdited] = useState(false)
    const slackEnabled = user && user.team && user.team.slack_incoming_webhook

    if (actionLoading || !action) return <Loading />

    const addGroup = (
        <button
            data-attr="match-group-button"
            type="button"
            className="btn btn-outline-success btn-sm"
            onClick={() => {
                setAction({ ...action, steps: [...action.steps, { isNew: uuid() }] })
            }}
        >
            Add another match group
        </button>
    )

    return (
        <div className={isEditor ? '' : 'card'} style={{ marginTop: isEditor ? 8 : '' }} data-attr="action-editor">
            <form
                className={isEditor ? '' : 'card-body'}
                onSubmit={e => {
                    e.preventDefault()
                    if (isEditor && showNewActionButton) setCreateNew(true)
                    saveAction()
                    updateOnboardingStep(0)
                }}
            >
                <input
                    required
                    className="form-control"
                    placeholder="For example: user signed up"
                    value={action.name}
                    onChange={e => {
                        setAction({ ...action, name: e.target.value })
                        setEdited(e.target.value ? true : false)
                    }}
                    data-attr="edit-action-input"
                />

                {action.count > -1 && (
                    <div>
                        <small className="text-muted">Matches {action.count} events</small>
                    </div>
                )}

                {!isEditor && <br />}

                {action.steps.map((step, index) => (
                    <Fragment key={index}>
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
                            isOnlyStep={action.steps.length === 1}
                            onDelete={() => {
                                setAction({ ...action, steps: action.steps.filter(s => s.id != step.id) })
                                setEdited(true)
                            }}
                            onChange={newStep => {
                                setAction({
                                    ...action,
                                    steps: action.steps.map(s =>
                                        (step.id && s.id == step.id) || (step.isNew && s.isNew === step.isNew)
                                            ? {
                                                  id: step.id,
                                                  isNew: step.isNew,
                                                  ...newStep,
                                              }
                                            : s
                                    ),
                                })
                                setEdited(true)
                            }}
                        />
                    </Fragment>
                ))}

                {!isEditor ? (
                    <div style={{ marginTop: 20, marginBottom: 15 }}>
                        <label className={slackEnabled ? '' : 'disabled'} style={{ marginRight: 5 }}>
                            <input
                                type="checkbox"
                                onChange={e => {
                                    setAction({ ...action, post_to_slack: e.target.checked })
                                    setEdited(true)
                                }}
                                checked={!!action.post_to_slack}
                                disabled={!slackEnabled}
                            />
                            &nbsp;Post to Slack/Teams when this action is triggered.
                        </label>
                        <Link to="/setup#slack">
                            <small>Configure</small>
                        </Link>
                    </div>
                ) : (
                    <br />
                )}

                {errorActionId && (
                    <p className="text-danger">
                        Action with this name already exists.{' '}
                        <a href={apiURL + 'action/' + errorActionId}>Click here to edit.</a>
                    </p>
                )}

                {isEditor ? <div style={{ marginBottom: 20 }}>{addGroup}</div> : null}

                <div className={isEditor ? 'btn-group save-buttons' : ''}>
                    {!isEditor ? addGroup : null}
                    <button
                        disabled={!edited}
                        data-attr="save-action-button"
                        className={
                            edited ? 'btn-success btn btn-sm float-right' : 'btn-secondary btn btn-sm float-right'
                        }
                    >
                        Save action
                    </button>
                </div>
            </form>
        </div>
    )
}
