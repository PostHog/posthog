import React, { useState, Fragment } from 'react'
import { uuid, Loading } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { useValues, useActions } from 'kea'
import { actionEditLogic } from './actionEditLogic'

import { ActionStep } from './ActionStep'
import { Input } from 'antd'

export function ActionEdit({ actionId, apiURL, onSave, user, isEditor, simmer, showNewActionButton, temporaryToken }) {
    let logic = actionEditLogic({
        id: actionId,
        apiURL,
        onSave: (action, createNew) => onSave(action, !actionId, createNew),
        temporaryToken,
    })
    const { action, actionLoading, errorActionId } = useValues(logic)
    const { setAction, saveAction, setCreateNew } = useActions(logic)

    const [edited, setEdited] = useState(false)
    const slackEnabled = user?.team?.slack_incoming_webhook

    if (actionLoading || !action) return <Loading />

    const addGroup = (
        <button
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
        <div className={isEditor ? '' : 'card'} style={{ marginTop: isEditor ? 8 : '' }}>
            <form
                className={isEditor ? '' : 'card-body'}
                onSubmit={(e) => {
                    e.preventDefault()
                    if (isEditor && showNewActionButton) setCreateNew(true)
                    saveAction()
                }}
            >
                <input
                    required
                    className="form-control"
                    placeholder="For example: user signed up"
                    value={action.name}
                    onChange={(e) => {
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
                                setAction({ ...action, steps: action.steps.filter((s) => s.id != step.id) })
                                setEdited(true)
                            }}
                            onChange={(newStep) => {
                                setAction({
                                    ...action,
                                    steps: action.steps.map((s) =>
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
                    <div>
                        <div style={{ margin: '1rem 0 0.5rem' }}>
                            <input
                                id="webhook-checkbox"
                                type="checkbox"
                                onChange={(e) => {
                                    setAction({ ...action, post_to_slack: e.target.checked })
                                    setEdited(true)
                                }}
                                checked={!!action.post_to_slack}
                                disabled={!slackEnabled}
                            />
                            <label
                                className={slackEnabled ? '' : 'disabled'}
                                style={{ marginLeft: '0.5rem', marginBottom: '0.5rem' }}
                                htmlFor="webhook-checkbox"
                            >
                                Post to Slack/Teams when this action is triggered.
                            </label>{' '}
                            <Link to="/setup#webhook">
                                {slackEnabled ? 'Configure' : 'Enable'} this integration in Setup.
                            </Link>
                            {action.post_to_slack && (
                                <>
                                    <Input
                                        addonBefore="Message format (optional)"
                                        placeholder="try: [action.name] triggered by [user.name]"
                                        value={action.slack_message_format}
                                        onChange={(e) => {
                                            setAction({ ...action, slack_message_format: e.target.value })
                                            setEdited(true)
                                        }}
                                        disabled={!slackEnabled || !action.post_to_slack}
                                        data-attr="edit-slack-message-format"
                                    />
                                    <small>
                                        <a
                                            href="https://posthog.com/docs/integrations/message-formatting/"
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            See documentation on how to format webhook messages.
                                        </a>
                                    </small>
                                </>
                            )}
                        </div>
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
