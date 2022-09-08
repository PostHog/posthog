import React from 'react'
import { compactNumber, uuid } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { useActions, useValues } from 'kea'
import { actionEditLogic, ActionEditLogicProps } from './actionEditLogic'
import './Actions.scss'
import { ActionStep } from './ActionStep'
import { Button, Col, Row } from 'antd'
import { InfoCircleOutlined, LoadingOutlined, PlusOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ActionStepType, AvailableFeature } from '~/types'
import { userLogic } from 'scenes/userLogic'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { Field } from 'lib/forms/Field'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { lemonToast } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'

export function ActionEdit({ action: loadedAction, id, onSave, temporaryToken }: ActionEditLogicProps): JSX.Element {
    const logicProps: ActionEditLogicProps = {
        id: id,
        action: loadedAction,
        onSave: (action) => onSave(action),
        temporaryToken,
    }
    const logic = actionEditLogic(logicProps)
    const { action, actionLoading, actionCount, actionCountLoading, shouldSimplifyActions } = useValues(logic)
    const { submitAction, deleteAction } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const slackEnabled = currentTeam?.slack_incoming_webhook

    const deleteButton = (): JSX.Element => (
        <LemonButton
            data-attr="delete-action-bottom"
            status="danger"
            type="secondary"
            onClick={() => {
                deleteAction()
            }}
        >
            Delete
        </LemonButton>
    )

    const cancelButton = (): JSX.Element => (
        <LemonButton
            data-attr="cancel-action-bottom"
            status="danger"
            type="secondary"
            onClick={() => {
                router.actions.push(shouldSimplifyActions ? urls.eventDefinitions() : urls.actions())
            }}
        >
            Cancel
        </LemonButton>
    )

    return (
        <div className="action-edit-container">
            <Form logic={actionEditLogic} props={logicProps} formKey="action" enableFormOnSubmit>
                <PageHeader
                    title={
                        <Field name="name">
                            {({ value, onChange }) => (
                                <EditableField
                                    name="name"
                                    value={value || ''}
                                    placeholder={`Name this ${shouldSimplifyActions ? 'calculated event' : 'action'}`}
                                    onChange={
                                        !id
                                            ? onChange
                                            : undefined /* When creating a new action, change value on type */
                                    }
                                    onSave={(value) => {
                                        onChange(value)
                                        submitAction()
                                        /* When clicking 'Save' on an `EditableField`, save the form too */
                                    }}
                                    mode={!id ? 'edit' : undefined /* When creating a new action, maintain edit mode */}
                                    minLength={1}
                                    maxLength={400} // Sync with action model
                                    data-attr={`action-name-${id ? 'edit' : 'create'}`}
                                    className="action-name"
                                />
                            )}
                        </Field>
                    }
                    caption={
                        <>
                            <Field name="description">
                                {({ value, onChange }) => (
                                    <EditableField
                                        multiline
                                        name="description"
                                        value={value || ''}
                                        placeholder="Description (optional)"
                                        onChange={
                                            !id
                                                ? onChange
                                                : undefined /* When creating a new action, change value on type */
                                        }
                                        onSave={(value) => {
                                            onChange(value)
                                            submitAction()
                                            /* When clicking 'Set' on an `EditableField`, always save the form */
                                        }}
                                        mode={
                                            !id
                                                ? 'edit'
                                                : undefined /* When creating a new action, maintain edit mode */
                                        }
                                        data-attr="action-description"
                                        className="action-description"
                                        compactButtons
                                        maxLength={600} // No limit on backend model, but enforce shortish description
                                        paywall={!hasAvailableFeature(AvailableFeature.INGESTION_TAXONOMY)}
                                    />
                                )}
                            </Field>
                            <Field name="tags">
                                {({ value, onChange }) => (
                                    <ObjectTags
                                        tags={value ?? []}
                                        onChange={(_, newTags) => onChange(newTags)}
                                        className="action-tags"
                                        saving={actionLoading}
                                    />
                                )}
                            </Field>
                        </>
                    }
                    buttons={!!id ? deleteButton() : cancelButton()}
                />
                {id && (
                    <div className="input-set">
                        <div>
                            <span className="text-muted mb-2">
                                {actionCountLoading && <LoadingOutlined />}
                                {actionCount !== null && actionCount > -1 && (
                                    <>
                                        This {shouldSimplifyActions ? 'calculated event' : 'action'} matches{' '}
                                        <b>{compactNumber(actionCount)}</b> events in the last 3 months
                                    </>
                                )}
                            </span>
                        </div>
                    </div>
                )}

                <div style={{ overflow: 'visible' }}>
                    <h2 className="subtitle">Match groups</h2>
                    <div>
                        Your {shouldSimplifyActions ? 'calculated event' : 'action'} will be triggered whenever{' '}
                        <b>any of your match groups</b> are received.{' '}
                        <a href="https://posthog.com/docs/features/actions" target="_blank">
                            <InfoCircleOutlined />
                        </a>
                    </div>
                    <Field name="steps">
                        {({ onChange }) => (
                            <div style={{ textAlign: 'right', marginBottom: 12 }}>
                                <Button
                                    onClick={() => onChange([...(action.steps || []), { isNew: uuid() }])}
                                    size="small"
                                >
                                    Add another match group
                                </Button>
                            </div>
                        )}
                    </Field>
                    <Field name="steps">
                        {({ value: stepsValue, onChange }) => (
                            <Row gutter={[24, 24]}>
                                <>
                                    {stepsValue.map((step: ActionStepType, index: number) => {
                                        const identifier = String(JSON.stringify(step))
                                        return (
                                            <ActionStep
                                                key={index}
                                                identifier={identifier}
                                                index={index}
                                                step={step}
                                                actionId={action.id || 0}
                                                isOnlyStep={!!stepsValue && stepsValue.length === 1}
                                                onDelete={() => {
                                                    const identifier = step.id ? 'id' : 'isNew'
                                                    onChange(
                                                        stepsValue?.filter(
                                                            (s: ActionStepType) => s[identifier] !== step[identifier]
                                                        ) ?? []
                                                    )
                                                }}
                                                onChange={(newStep) => {
                                                    onChange(
                                                        stepsValue?.map((s: ActionStepType) =>
                                                            (step.id && s.id == step.id) ||
                                                            (step.isNew && s.isNew === step.isNew)
                                                                ? {
                                                                      id: step.id,
                                                                      isNew: step.isNew,
                                                                      ...newStep,
                                                                  }
                                                                : s
                                                        ) ?? []
                                                    )
                                                }}
                                            />
                                        )
                                    })}
                                </>

                                <Col span={24} md={12}>
                                    <div
                                        className="match-group-add-skeleton"
                                        onClick={() => {
                                            onChange([...(action.steps || []), { isNew: uuid() }])
                                        }}
                                    >
                                        <PlusOutlined style={{ fontSize: 28, color: '#666666' }} />
                                    </div>
                                </Col>
                            </Row>
                        )}
                    </Field>
                </div>
                <div className="my-8">
                    <Field name="post_to_slack">
                        {({ value, onChange }) => (
                            <>
                                <LemonCheckbox
                                    id="webhook-checkbox"
                                    checked={!!value}
                                    onChange={onChange}
                                    disabled={!slackEnabled}
                                    label={
                                        <>
                                            Post to webhook when this{' '}
                                            {shouldSimplifyActions ? 'calculated event' : 'action'} is triggered.
                                        </>
                                    }
                                />
                                <p className="pl-7">
                                    <Link to="/project/settings#webhook">
                                        {slackEnabled ? 'Configure' : 'Enable'} this integration in Setup.
                                    </Link>
                                </p>
                            </>
                        )}
                    </Field>
                    {action.post_to_slack && (
                        <>
                            <Field name="slack_message_format">
                                {({ value, onChange }) => (
                                    <>
                                        <LemonLabel showOptional>Message format</LemonLabel>
                                        <LemonInput
                                            placeholder="Default: [action.name] triggered by [person]"
                                            value={value}
                                            onChange={onChange}
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
                            </Field>
                        </>
                    )}
                </div>
                <div className="flex justify-end gap-2">
                    {!!id ? deleteButton() : cancelButton()}
                    <LemonButton
                        data-attr="save-action-button"
                        type="primary"
                        htmlType="submit"
                        loading={actionLoading}
                    >
                        Save
                    </LemonButton>
                </div>
            </Form>
        </div>
    )
}

// TODO: remove when "simplify-actions" FF is released
export function duplicateActionErrorToast(errorActionId: string, shouldSimplifyActions: boolean): void {
    lemonToast.error(
        <>
            {shouldSimplifyActions ? 'Calculated event' : 'Action'} with this name already exists.{' '}
            <a href={urls.action(errorActionId)}>Click here to edit.</a>
        </>
    )
}
