// Experiment actions-ux-201012

import React, { useState } from 'react'
import { uuid, Loading } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { useValues, useActions } from 'kea'
import { actionEditLogic } from './actionEditLogic'
import './Actions.scss'
import { ActionStep } from './ActionStepV2'
import { Col, Input, Row } from 'antd'
import { InfoCircleOutlined, PlusOutlined } from '@ant-design/icons'

export function ActionEdit({ actionId, apiURL, onSave, user, simmer, temporaryToken }) {
    let logic = actionEditLogic({
        id: actionId,
        apiURL,
        onSave: (action, createNew) => onSave(action, !actionId, createNew),
        temporaryToken,
    })
    const { action, actionLoading, errorActionId } = useValues(logic)
    const { setAction, saveAction } = useActions(logic)

    const [edited, setEdited] = useState(false)
    const slackEnabled = user?.team?.slack_incoming_webhook

    if (actionLoading || !action) return <Loading />

    const newAction = () => {
        setAction({ ...action, steps: [...action.steps, { isNew: uuid() }] })
    }

    const addGroup = (
        <button type="button" className="btn btn-outline-success btn-sm" onClick={newAction}>
            Add another match group
        </button>
    )

    return (
        <div className="action-edit-container">
            <form
                onSubmit={(e) => {
                    e.preventDefault()
                    saveAction()
                }}
            >
                <label>Action name:</label>
                <input
                    required
                    className="form-control"
                    placeholder="e.g. user account created, purchase completed, movie watched"
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

                <div className="match-group-section card" style={{ overflow: 'visible' }}>
                    <h3>Match groups</h3>
                    <div>
                        Your action will be triggered whenever <b>any of your match groups</b> are received.{' '}
                        <a href="https://posthog.com/docs/features/actions" target="_blank">
                            <InfoCircleOutlined />
                        </a>
                    </div>
                    <div style={{ textAlign: 'right', marginBottom: 12 }}>{addGroup}</div>

                    <Row gutter={[24, 24]}>
                        {action.steps.map((step, index) => (
                            <ActionStep
                                key={step.id || step.isNew}
                                identifier={step.id || step.isNew}
                                index={index}
                                step={step}
                                isEditor={false}
                                actionId={action.id}
                                simmer={simmer}
                                isOnlyStep={action.steps.length === 1}
                                onDelete={() => {
                                    const identifier = step.id ? 'id' : 'isNew'
                                    setAction({
                                        ...action,
                                        steps: action.steps.filter((s) => s[identifier] !== step[identifier]),
                                    })
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
                        ))}
                        <Col span={24} md={12}>
                            <div className="match-group-add-skeleton" onClick={newAction}>
                                <PlusOutlined style={{ fontSize: 28, color: '#666666' }} />
                            </div>
                        </Col>
                    </Row>
                </div>
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
                {errorActionId && (
                    <p className="text-danger">
                        Action with this name already exists.{' '}
                        <a href={apiURL + 'action/' + errorActionId}>Click here to edit.</a>
                    </p>
                )}
                <div>
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
