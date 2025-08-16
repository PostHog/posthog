import { IconInfo, IconPlus, IconRewindPlay, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { NotFound } from 'lib/components/NotFound'
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
import { ActionHogFunctions } from '../components/ActionHogFunctions'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActions, ScenePanelDivider, ScenePanelMetaInfo } from '~/layout/scenes/SceneLayout'

import { tagsModel } from '~/models/tagsModel'
import { ActionStepType, FilterLogicalOperator, ProductKey, ReplayTabs } from '~/types'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { actionEditLogic, ActionEditLogicProps, DEFAULT_ACTION_STEP } from '../logics/actionEditLogic'
import { ActionStep } from '../components/ActionStep'
import { SceneTitleSection, SceneSection, SceneDivider, SceneContent } from '~/layout/scenes/SceneContent'
import { actionLogic } from '../logics/actionLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
const RESOURCE_TYPE = 'action'

export interface ActionEditProps extends ActionEditLogicProps {
    actionLoading?: boolean
}

export function ActionEdit({ action: loadedAction, id, actionLoading }: ActionEditProps): JSX.Element {
    const logicProps: ActionEditLogicProps = {
        id: id,
        action: loadedAction,
    }
    const { isComplete } = useValues(actionLogic({ id }))
    const logic = actionEditLogic(logicProps)
    const { action, actionChanged } = useValues(logic)
    const { submitAction, deleteAction, setActionValue, setAction } = useActions(logic)

    // Sync the loaded action prop with the logic's internal state
    useEffect(() => {
        if (loadedAction && (!action || action.id !== loadedAction.id)) {
            setAction(loadedAction, { merge: false })
        }
    }, [loadedAction, action, setAction])
    const { tags } = useValues(tagsModel)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    // Handle 404 when loading is done and action is missing
    if (id && !actionLoading && !loadedAction) {
        return <NotFound object="action" />
    }

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

    return (
        <SceneContent>
            <Form
                logic={actionEditLogic}
                props={logicProps}
                formKey="action"
                enableFormOnSubmit
                className="flex flex-col gap-y-4"
            >
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

                <SceneTitleSection
                    name={action.name}
                    description={action.description}
                    resourceType={{
                        to: urls.actions(),
                        type: RESOURCE_TYPE,
                        tooltip: 'Go to all actions',
                        typePlural: 'actions',
                    }}
                    markdown={true}
                    isLoading={actionLoading}
                    onNameBlur={(value) => {
                        setActionValue('name', value)
                    }}
                    onDescriptionBlur={(value) => {
                        setActionValue('description', value)
                    }}
                    docsURL="https://posthog.com/docs/data/actions"
                />

                <SceneDivider />

                <SceneSection
                    title="Match groups"
                    className="@container"
                    description={
                        <>
                            Your action will be triggered whenever <b>any of your match groups</b> are received.
                            <Link to="https://posthog.com/docs/data/actions" target="_blank">
                                <IconInfo className="ml-1 text-secondary text-xl" />
                            </Link>
                        </>
                    }
                >
                    {actionLoading ? (
                        <div className="flex gap-2">
                            <LemonSkeleton className="w-1/2 h-[261px]" />
                            <LemonSkeleton className="w-1/2 h-[261px]" />
                        </div>
                    ) : (
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
                    )}
                </SceneSection>
            </Form>
            <SceneDivider />
            <ActionHogFunctions />
            <SceneDivider />
            {id && (
                <>
                    <SceneSection
                        className="@container"
                        title="Matching events"
                        description={
                            <>
                                This is the list of <strong>recent</strong> events that match this action.
                            </>
                        }
                    >
                        {isComplete ? (
                            <Query
                                query={{
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.EventsQuery,
                                        select: defaultDataTableColumns(NodeKind.EventsQuery),
                                        actionId: id,
                                        after: '-24h',
                                    },
                                    full: true,
                                    showEventFilter: false,
                                    showPropertyFilter: false,
                                }}
                            />
                        ) : (
                            <div className="flex items-center">
                                <Spinner className="mr-4" />
                                Calculating action, please hold on...
                            </div>
                        )}
                    </SceneSection>
                </>
            )}
        </SceneContent>
    )
}
