import { IconInfo, IconPlus, IconRewindPlay, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { ActionHogFunctions } from 'scenes/actions/ActionHogFunctions'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { ScenePanel, ScenePanelActions, ScenePanelDivider, ScenePanelMetaInfo } from '~/layout/scenes/SceneLayout'

import { tagsModel } from '~/models/tagsModel'
import { ActionStepType, FilterLogicalOperator, ProductKey, ReplayTabs } from '~/types'

import { SceneTextarea } from 'lib/components/Scenes/SceneTextarea'
import { SceneTextInput } from 'lib/components/Scenes/SceneTextInput'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { actionEditLogic, ActionEditLogicProps, DEFAULT_ACTION_STEP } from './actionEditLogic'
import { ActionStep } from './ActionStep'

const RESOURCE_TYPE = 'action'

export function ActionEdit({ action: loadedAction, id }: ActionEditLogicProps): JSX.Element {
    const logicProps: ActionEditLogicProps = {
        id: id,
        action: loadedAction,
    }
    const logic = actionEditLogic(logicProps)
    const { action, actionLoading, actionChanged } = useValues(logic)
    const { submitAction, deleteAction, setActionValue } = useActions(logic)
    const { tags } = useValues(tagsModel)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

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
            tooltip="Cancel and return to the list of actions"
        >
            Cancel
        </LemonButton>
    )

    const actionEditJSX = (
        <div className="action-edit-container">
            <Form logic={actionEditLogic} props={logicProps} formKey="action" enableFormOnSubmit>
                <PageHeader
                    caption={
                        <>
                            {!newSceneLayout && (
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
                                            />
                                        )}
                                    </LemonField>
                                    <LemonField name="tags" className="mt-2">
                                        {({ value, onChange }) => (
                                            <ObjectTags
                                                tags={value ?? []}
                                                onChange={(tags) => onChange(tags)}
                                                className="action-tags"
                                                saving={actionLoading}
                                                tagsAvailable={tags.filter((tag) => !action.tags?.includes(tag))}
                                            />
                                        )}
                                    </LemonField>
                                </>
                            )}
                        </>
                    }
                    buttons={
                        <>
                            {!newSceneLayout && id && (
                                <LemonButton
                                    type="secondary"
                                    to={urls.replay(ReplayTabs.Home, {
                                        filter_group: {
                                            type: FilterLogicalOperator.And,
                                            values: [
                                                {
                                                    type: FilterLogicalOperator.And,
                                                    values: [
                                                        {
                                                            id: id,
                                                            type: 'actions',
                                                            order: 0,
                                                            name: action.name,
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                    })}
                                    onClick={() => {
                                        addProductIntentForCrossSell({
                                            from: ProductKey.ACTIONS,
                                            to: ProductKey.SESSION_REPLAY,
                                            intent_context: ProductIntentContext.ACTION_VIEW_RECORDINGS,
                                        })
                                    }}
                                    sideIcon={<IconPlayCircle />}
                                    data-attr="action-view-recordings"
                                >
                                    View recordings
                                </LemonButton>
                            )}
                            {/* Existing action */}
                            {!newSceneLayout && (
                                <>
                                    {id && deleteButton()}
                                    {!id && cancelButton()}
                                </>
                            )}
                            {/* New action */}
                            {newSceneLayout && <>{!id && cancelButton()}</>}
                            {/* Existing action */}
                            {!newSceneLayout && (actionChanged || !id) ? (
                                <LemonButton
                                    data-attr="save-action-button"
                                    type="primary"
                                    htmlType="submit"
                                    loading={actionLoading}
                                    onClick={() => {
                                        if (id) {
                                            submitAction()
                                        } else {
                                            setActionValue('_create_in_folder', 'Unfiled/Insights')
                                            submitAction()
                                        }
                                    }}
                                    disabledReason={!actionChanged && !id ? 'No changes to save' : undefined}
                                >
                                    Save
                                </LemonButton>
                            ) : null}
                            {/* New action */}
                            {newSceneLayout ? (
                                <LemonButton
                                    data-attr="save-action-button"
                                    type="primary"
                                    htmlType="submit"
                                    loading={actionLoading}
                                    onClick={() => {
                                        if (id) {
                                            submitAction()
                                        } else {
                                            setActionValue('_create_in_folder', 'Unfiled/Insights')
                                            submitAction()
                                        }
                                    }}
                                    disabledReason={!actionChanged ? 'No changes to save' : undefined}
                                >
                                    {actionChanged ? 'Save' : 'No changes'}
                                </LemonButton>
                            ) : null}
                        </>
                    }
                />

                <ScenePanel>
                    <ScenePanelMetaInfo>
                        <SceneTextInput
                            name="name"
                            defaultValue={action.name || ''}
                            dataAttrKey={RESOURCE_TYPE}
                            onSave={(value) => {
                                setActionValue('name', value)
                            }}
                            isLoading={actionLoading}
                        />

                        <SceneTextarea
                            name="description"
                            defaultValue={action.description || ''}
                            onSave={(value) => setActionValue('description', value)}
                            dataAttrKey={RESOURCE_TYPE}
                            optional
                            isLoading={actionLoading}
                            markdown
                        />

                        <SceneTags
                            onSave={(tags) => {
                                setActionValue('tags', tags)
                            }}
                            tags={action.tags || []}
                            tagsAvailable={tags}
                            dataAttrKey={RESOURCE_TYPE}
                        />

                        <SceneFile dataAttrKey={RESOURCE_TYPE} />

                        <SceneActivityIndicator at={action.created_at} by={action.created_by} prefix="Created" />
                    </ScenePanelMetaInfo>
                    <ScenePanelDivider />

                    <ScenePanelActions>
                        {id && (
                            <>
                                <Link
                                    to={urls.replay(ReplayTabs.Home, {
                                        filter_group: {
                                            type: FilterLogicalOperator.And,
                                            values: [
                                                {
                                                    type: FilterLogicalOperator.And,
                                                    values: [
                                                        {
                                                            id: id,
                                                            type: 'actions',
                                                            order: 0,
                                                            name: action.name,
                                                        },
                                                    ],
                                                },
                                            ],
                                        },
                                    })}
                                    onClick={() => {
                                        addProductIntentForCrossSell({
                                            from: ProductKey.ACTIONS,
                                            to: ProductKey.SESSION_REPLAY,
                                            intent_context: ProductIntentContext.ACTION_VIEW_RECORDINGS,
                                        })
                                    }}
                                    data-attr={`${RESOURCE_TYPE}-view-recordings`}
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                >
                                    <IconRewindPlay />
                                    View recordings
                                </Link>
                                <ScenePanelDivider />
                            </>
                        )}

                        <ButtonPrimitive
                            onClick={() => {
                                deleteAction()
                            }}
                            variant="danger"
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-delete`}
                        >
                            <IconTrash />
                            Delete
                        </ButtonPrimitive>
                    </ScenePanelActions>
                </ScenePanel>

                <div className="@container">
                    <h2 className="subtitle">Match groups</h2>
                    <p>
                        Your action will be triggered whenever <b>any of your match groups</b> are received.
                        <Link to="https://posthog.com/docs/data/actions" target="_blank">
                            <IconInfo className="ml-1 text-secondary text-xl" />
                        </Link>
                    </p>
                    <LemonField name="steps">
                        {({ value: stepsValue, onChange }) => (
                            <div className="grid @4xl:grid-cols-2 gap-3">
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
                                                const newSteps = [...stepsValue]
                                                newSteps.splice(index, 1)
                                                onChange(newSteps)
                                            }}
                                            onChange={(newStep) => {
                                                const newSteps = [...stepsValue]
                                                newSteps.splice(index, 1, newStep)
                                                onChange(newSteps)
                                            }}
                                        />
                                    )
                                })}

                                <div>
                                    <LemonButton
                                        icon={<IconPlus />}
                                        type="secondary"
                                        onClick={() => {
                                            onChange([...(action.steps || []), DEFAULT_ACTION_STEP])
                                        }}
                                        center
                                        className="w-full h-full"
                                    >
                                        Add match group
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                    </LemonField>
                </div>
            </Form>
        </div>
    )

    return (
        <>
            {actionEditJSX}
            <ActionHogFunctions />
        </>
    )
}
