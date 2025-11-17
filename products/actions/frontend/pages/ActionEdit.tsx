import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconInfo, IconPlus, IconRewindPlay, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { Query } from '~/queries/Query/Query'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActionStepType,
    FilterLogicalOperator,
    ProductKey,
    ReplayTabs,
} from '~/types'

import { ActionHogFunctions } from '../components/ActionHogFunctions'
import { ActionStep } from '../components/ActionStep'
import { ActionEditLogicProps, DEFAULT_ACTION_STEP, actionEditLogic } from '../logics/actionEditLogic'
import { actionLogic } from '../logics/actionLogic'

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

    // Check if user can edit this action
    const canEdit = userHasAccess(AccessControlResourceType.Action, AccessControlLevel.Editor, action.user_access_level)
    const cannotEditReason = getAccessControlDisabledReason(
        AccessControlResourceType.Action,
        AccessControlLevel.Editor,
        action.user_access_level
    )

    const actionId = typeof action?.id === 'number' ? action.id : null

    useFileSystemLogView({
        type: 'action',
        ref: actionId,
        enabled: Boolean(actionId && !actionLoading),
        deps: [actionId, actionLoading],
    })

    // Handle 404 when loading is done and action is missing
    if (id && !actionLoading && !loadedAction) {
        return <NotFound object="action" />
    }

    const cancelButton = (): JSX.Element => (
        <LemonButton
            data-attr="cancel-action-bottom"
            status="danger"
            type="secondary"
            onClick={() => {
                router.actions.push(urls.actions())
            }}
            tooltip="Cancel and return to the list of actions"
            size="small"
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
                <ScenePanel>
                    <ScenePanelInfoSection>
                        <SceneTags
                            onSave={(tags) => {
                                setActionValue('tags', tags)
                            }}
                            tags={action.tags || []}
                            tagsAvailable={tags}
                            dataAttrKey={RESOURCE_TYPE}
                            canEdit={canEdit}
                        />

                        <SceneFile dataAttrKey={RESOURCE_TYPE} />

                        <SceneActivityIndicator at={action.created_at} by={action.created_by} prefix="Created" />
                    </ScenePanelInfoSection>
                    <ScenePanelDivider />

                    <ScenePanelActionsSection>
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
                            </>
                        )}
                    </ScenePanelActionsSection>
                    <ScenePanelDivider />
                    <ScenePanelActionsSection>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Action}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {({ disabledReason }) => (
                                <ButtonPrimitive
                                    onClick={() => {
                                        deleteAction()
                                    }}
                                    variant="danger"
                                    menuItem
                                    data-attr={`${RESOURCE_TYPE}-delete`}
                                    disabled={!!disabledReason}
                                    {...(disabledReason && { tooltip: disabledReason })}
                                >
                                    <IconTrash />
                                    Delete
                                </ButtonPrimitive>
                            )}
                        </AccessControlAction>
                    </ScenePanelActionsSection>
                </ScenePanel>

                <SceneTitleSection
                    name={action?.name || ''}
                    description={action.description}
                    resourceType={{
                        to: urls.actions(),
                        type: RESOURCE_TYPE,
                    }}
                    markdown={true}
                    isLoading={actionLoading}
                    onNameChange={(value) => {
                        setActionValue('name', value)
                    }}
                    onDescriptionChange={(value) => {
                        setActionValue('description', value)
                    }}
                    canEdit={canEdit}
                    forceEdit={!id}
                    actions={
                        <>
                            {!id && cancelButton()}
                            <LemonButton
                                data-attr="save-action-button"
                                type="primary"
                                htmlType="submit"
                                loading={actionLoading}
                                onClick={(e) => {
                                    e.preventDefault()
                                    if (id) {
                                        submitAction()
                                    } else {
                                        setActionValue('_create_in_folder', 'Unfiled/Insights')
                                        submitAction()
                                    }
                                }}
                                size="small"
                                disabledReason={!actionChanged ? 'No changes to save' : undefined}
                            >
                                {actionChanged ? 'Save' : 'No changes'}
                            </LemonButton>
                        </>
                    }
                />

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
                                                disabledReason={cannotEditReason ?? undefined}
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
                                            disabledReason={cannotEditReason ?? undefined}
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
