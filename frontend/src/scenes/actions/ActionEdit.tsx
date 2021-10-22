import React, { useState } from 'react'
import { uuid, deleteWithUndo, compactNumber } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { useValues, useActions } from 'kea'
import { actionEditLogic, ActionEditLogicProps } from './actionEditLogic'
import './Actions.scss'
import { ActionStep } from './ActionStep'
import { Button, Col, Input, Row } from 'antd'
import { InfoCircleOutlined, PlusOutlined, SaveOutlined, DeleteOutlined, LoadingOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { actionsModel } from '~/models/actionsModel'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import dayjs from 'dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function ActionEdit({ action: loadedAction, id, onSave, temporaryToken }: ActionEditLogicProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const relevantActionEditLogic = actionEditLogic({
        id: id,
        action: loadedAction,
        onSave: (action) => onSave(action),
        temporaryToken,
    })
    const { action, errorActionId, actionCount, actionCountLoading } = useValues(relevantActionEditLogic)
    const { setAction, saveAction } = useActions(relevantActionEditLogic)
    const { loadActions } = useActions(actionsModel)
    const { preflight } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)

    const [edited, setEdited] = useState(false)
    const slackEnabled = currentTeam?.slack_incoming_webhook

    function addMatchGroup(): void {
        setAction({ ...action, steps: [...(action.steps || []), { isNew: uuid() }] })
    }

    const addGroup = (
        <Button onClick={addMatchGroup} size="small">
            Add another match group
        </Button>
    )

    const deleteAction = id ? (
        <Button
            data-attr="delete-action"
            danger
            icon={<DeleteOutlined />}
            onClick={() => {
                deleteWithUndo({
                    endpoint: `projects/${currentTeamId}/actions`,
                    object: action,
                    callback: () => {
                        router.actions.push('/events/actions')
                        loadActions()
                    },
                })
            }}
        >
            Delete
        </Button>
    ) : undefined

    return (
        <div className="action-edit-container">
            <PageHeader title={id ? 'Editing action' : 'Creating action'} buttons={deleteAction} />
            <form
                onSubmit={(e) => {
                    e.preventDefault()
                    saveAction()
                }}
            >
                <div className="input-set">
                    <label htmlFor="actionName">Action name</label>
                    <Input
                        required
                        placeholder="e.g. user account created, purchase completed, movie watched"
                        value={action.name}
                        style={{ maxWidth: 500, display: 'block' }}
                        onChange={(e) => {
                            setAction({ ...action, name: e.target.value })
                            setEdited(e.target.value ? true : false)
                        }}
                        data-attr="edit-action-input"
                        id="actionName"
                    />
                    {id && (
                        <div>
                            <span className="text-muted mb-05">
                                {actionCountLoading && <LoadingOutlined />}
                                {actionCount !== null && actionCount > -1 && (
                                    <>
                                        This action matches <b>{compactNumber(actionCount)}</b> events
                                        {preflight?.db_backend !== 'clickhouse' && action.last_calculated_at && (
                                            <>
                                                {' (last calculated '}
                                                <b>{dayjs(action.last_calculated_at).fromNow()}</b>
                                                {')'}
                                            </>
                                        )}
                                    </>
                                )}
                            </span>
                        </div>
                    )}
                </div>

                <div className="match-group-section" style={{ overflow: 'visible' }}>
                    <h2 className="subtitle">Match groups</h2>
                    <div>
                        Your action will be triggered whenever <b>any of your match groups</b> are received.{' '}
                        <a href="https://posthog.com/docs/features/actions" target="_blank">
                            <InfoCircleOutlined />
                        </a>
                    </div>
                    <div style={{ textAlign: 'right', marginBottom: 12 }}>{addGroup}</div>

                    <Row gutter={[24, 24]}>
                        {action.steps?.map((step, index) => (
                            <ActionStep
                                key={step.id || step.isNew}
                                identifier={String(step.id || step.isNew)}
                                index={index}
                                step={step}
                                actionId={action.id || 0}
                                isOnlyStep={!!action.steps && action.steps.length === 1}
                                onDelete={() => {
                                    const identifier = step.id ? 'id' : 'isNew'
                                    setAction({
                                        ...action,
                                        steps: action.steps?.filter((s) => s[identifier] !== step[identifier]),
                                    })
                                    setEdited(true)
                                }}
                                onChange={(newStep) => {
                                    setAction({
                                        ...action,
                                        steps: action.steps?.map((s) =>
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
                            <div className="match-group-add-skeleton" onClick={addMatchGroup}>
                                <PlusOutlined style={{ fontSize: 28, color: '#666666' }} />
                            </div>
                        </Col>
                    </Row>
                </div>
                <div>
                    <div style={{ margin: '1rem 0' }}>
                        <p>
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
                                Post to webhook when this action is triggered.
                            </label>{' '}
                            <Link to="/project/settings#webhook">
                                {slackEnabled ? 'Configure' : 'Enable'} this integration in Setup.
                            </Link>
                        </p>
                        {action.post_to_slack && (
                            <>
                                <Input
                                    addonBefore="Message format (optional)"
                                    placeholder="Default: [action.name] triggered by [user.name]"
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
                        <a href={urls.action(errorActionId)}>Click here to edit.</a>
                    </p>
                )}
                <div className="float-right">
                    <span data-attr="delete-action-bottom">{deleteAction}</span>
                    <Button
                        disabled={!edited}
                        data-attr="save-action-button"
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={saveAction}
                        style={{ marginLeft: 16 }}
                    >
                        Save action
                    </Button>
                </div>
            </form>
        </div>
    )
}
