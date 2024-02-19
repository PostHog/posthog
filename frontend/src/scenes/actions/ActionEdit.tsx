import { LemonBanner, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { combineUrl, router } from 'kea-router'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { IconInfo, IconPlayCircle, IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { compactNumber, uuid } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { tagsModel } from '~/models/tagsModel'
import { ActionStepType, AvailableFeature } from '~/types'

import { actionEditLogic, ActionEditLogicProps } from './actionEditLogic'
import { ActionStep } from './ActionStep'
import { ActionWebhooks } from './webhooks/ActionWebhooks'

export function ActionEdit({ action: loadedAction, id }: ActionEditLogicProps): JSX.Element {
    const logicProps: ActionEditLogicProps = {
        id: id,
        action: loadedAction,
    }
    const logic = actionEditLogic(logicProps)
    const { action, actionLoading, actionCount, actionCountLoading } = useValues(logic)
    const { submitAction, deleteAction, setActionValue } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { tags } = useValues(tagsModel)

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
                router.actions.push(urls.actions())
            }}
        >
            Cancel
        </LemonButton>
    )

    return (
        <div className="action-edit-container">
            <Form logic={actionEditLogic} props={logicProps} formKey="action" enableFormOnSubmit>
                <PageHeader
                    caption={
                        <>
                            <LemonField name="description">
                                {({ value, onChange }) => (
                                    <EditableField
                                        multiline
                                        name="description"
                                        markdown
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
                            </LemonField>
                            <LemonField name="tags" className="mt-2">
                                {({ value, onChange }) => (
                                    <ObjectTags
                                        tags={value ?? []}
                                        onChange={(_, newTags) => onChange(newTags)}
                                        className="action-tags"
                                        saving={actionLoading}
                                        tagsAvailable={tags.filter((tag) => !action.tags?.includes(tag))}
                                    />
                                )}
                            </LemonField>
                        </>
                    }
                    buttons={
                        <>
                            {id ? (
                                <LemonButton
                                    type="secondary"
                                    to={
                                        combineUrl(urls.replay(), {
                                            filters: {
                                                actions: [
                                                    {
                                                        id: id,
                                                        type: 'actions',
                                                        order: 0,
                                                        name: action.name,
                                                    },
                                                ],
                                            },
                                        }).url
                                    }
                                    sideIcon={<IconPlayCircle />}
                                    data-attr="action-view-recordings"
                                >
                                    View recordings
                                </LemonButton>
                            ) : null}
                            {id ? deleteButton() : cancelButton()}
                            <LemonButton
                                data-attr="save-action-button"
                                type="primary"
                                htmlType="submit"
                                loading={actionLoading}
                                onClick={submitAction}
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                />
                {id && (
                    <div className="input-set">
                        <div>
                            <span className="flex items-center gap-2 text-muted mb-2">
                                {actionCount !== null && actionCount > -1 && (
                                    <span>
                                        This action matches <b>{compactNumber(actionCount)}</b> events in the last 3
                                        months
                                    </span>
                                )}
                                {actionCountLoading && <Spinner />}
                            </span>
                        </div>
                    </div>
                )}

                <div>
                    <h2 className="subtitle">Match groups</h2>
                    <p>
                        Your action will be triggered whenever <b>any of your match groups</b> are received.
                        <Link to="https://posthog.com/docs/features/actions" target="_blank">
                            <IconInfo className="ml-1 text-muted text-xl" />
                        </Link>
                    </p>
                    <LemonField name="steps">
                        {({ value: stepsValue, onChange }) => (
                            <div className="grid lg:grid-cols-2 gap-3">
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

                                <div>
                                    <LemonButton
                                        icon={<IconPlus />}
                                        onClick={() => {
                                            onChange([...(action.steps || []), { isNew: uuid() }])
                                        }}
                                        center
                                        className="w-full h-full border-dashed border"
                                    >
                                        Add match group
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                    </LemonField>
                </div>
                <div className="my-8">
                    <div className="flex gap-2 items-start justify-between">
                        <div className="flex-1">
                            <h2 className="subtitle flex items-start justify-between">Action webhooks</h2>
                            <p>Send webhooks whenever this action is triggered. </p>
                        </div>

                        <LemonButton type="secondary">Add webhook</LemonButton>
                    </div>

                    {id ? (
                        <ActionWebhooks actionId={id} />
                    ) : (
                        <LemonBanner type="info">
                            Please save your Action first and then you can configure webhooks for it.
                        </LemonBanner>
                    )}

                    {action.post_to_slack && (
                        <>
                            <LemonBanner
                                type="warning"
                                className="my-4"
                                action={{
                                    children: 'Remove webhook',
                                    onClick: () => setActionValue('post_to_slack', false),
                                }}
                            >
                                Your current webhook configuration is deprecated. We recommend removing it and creating
                                a new Action Webhook above.
                            </LemonBanner>
                            {!action.bytecode_error && action.post_to_slack && (
                                <>
                                    <LemonField name="slack_message_format">
                                        {({ value, onChange }) => (
                                            <>
                                                <LemonLabel showOptional>Slack message format (deprecated)</LemonLabel>
                                                <LemonTextArea
                                                    placeholder="Default: [action.name] triggered by [person]"
                                                    value={value}
                                                    onChange={onChange}
                                                    disabled={!slackEnabled || !action.post_to_slack}
                                                    data-attr="edit-slack-message-format"
                                                />
                                                <small>
                                                    <Link
                                                        to="https://posthog.com/docs/integrate/webhooks/message-formatting"
                                                        target="_blank"
                                                    >
                                                        See documentation on how to format webhook messages.
                                                    </Link>
                                                </small>
                                            </>
                                        )}
                                    </LemonField>
                                </>
                            )}
                        </>
                    )}
                </div>
            </Form>
        </div>
    )
}
