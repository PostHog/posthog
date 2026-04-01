import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonCollapse } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { tagsModel } from '~/models/tagsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, ActionStepType, FilterLogicalOperator } from '~/types'

import { ActionHogFunctions } from '../components/ActionHogFunctions'
import { ActionStep } from '../components/ActionStep'
import {
    ActionEditLogicProps,
    ActionReference,
    DEFAULT_ACTION_STEP,
    REFERENCE_TYPE_LABELS,
    actionEditLogic,
} from '../logics/actionEditLogic'
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
    const { action, actionChanged, references } = useValues(logic)
    const { submitAction, deleteAction, setActionValue, setAction } = useActions(logic)

    // Sync the loaded action prop with the logic's internal state
    useEffect(() => {
        if (loadedAction && (!action || action.id !== loadedAction.id)) {
            setAction(loadedAction, { merge: false })
        }
    }, [loadedAction, action, setAction])
    const { tags } = useValues(tagsModel)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)

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
    })

    // Handle 404 when loading is done and action is missing
    if (id && !actionLoading && !loadedAction) {
        return <NotFound object="action" />
    }

    const cancelButton = (): JSX.Element => (
        <LemonButton
            data-attr="cancel-action-bottom"
            type="tertiary"
            status="danger"
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
                            <ViewRecordingsPlaylistButton
                                filters={{
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
                                }}
                                onClick={() => {
                                    addProductIntentForCrossSell({
                                        from: ProductKey.ACTIONS,
                                        to: ProductKey.SESSION_REPLAY,
                                        intent_context: ProductIntentContext.ACTION_VIEW_RECORDINGS,
                                    })
                                }}
                                data-attr={`${RESOURCE_TYPE}-view-recordings`}
                            />
                        )}
                        {actionId && canCopyToProject && (
                            <ButtonPrimitive
                                menuItem
                                onClick={() => router.actions.push(urls.resourceTransfer('Action', actionId))}
                                data-attr="action-copy-to-project"
                                tooltip="Copy this action to another project"
                            >
                                <IconCopy />
                                Copy to another project
                            </ButtonPrimitive>
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
            <ActionHogFunctions />
            {id && references.length > 0 && (
                <>
                    <LemonCollapse
                        defaultActiveKey="used-by"
                        panels={[
                            {
                                key: 'used-by',
                                header: {
                                    children: (
                                        <div className="py-1">
                                            <div className="font-semibold">Used by</div>
                                            <div className="text-secondary text-sm font-normal">
                                                Resources that reference this action.
                                            </div>
                                        </div>
                                    ),
                                },
                                content: <ReferencesList logicProps={logicProps} />,
                            },
                        ]}
                    />
                </>
            )}
            {(id || action.steps?.length) && (
                <>
                    <LemonCollapse
                        defaultActiveKey="matching-events"
                        panels={[
                            {
                                key: 'matching-events',
                                header: {
                                    children: (
                                        <div className="py-1">
                                            <div className="font-semibold">Matching events</div>
                                            <div className="text-secondary text-sm font-normal">
                                                Recent events that match this action.
                                            </div>
                                        </div>
                                    ),
                                },
                                content:
                                    id && !isComplete && !actionChanged ? (
                                        <div className="flex items-center">
                                            <Spinner className="mr-4" />
                                            Calculating action, please hold on...
                                        </div>
                                    ) : (
                                        <Query
                                            query={{
                                                kind: NodeKind.DataTableNode,
                                                source: {
                                                    kind: NodeKind.EventsQuery,
                                                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                                                    ...(id && !actionChanged
                                                        ? { actionId: id }
                                                        : {
                                                              actionSteps: action.steps?.map(
                                                                  ({
                                                                      event,
                                                                      properties,
                                                                      selector,
                                                                      tag_name,
                                                                      text,
                                                                      text_matching,
                                                                      href,
                                                                      href_matching,
                                                                      url,
                                                                      url_matching,
                                                                  }) => ({
                                                                      event,
                                                                      properties,
                                                                      selector,
                                                                      tag_name,
                                                                      text,
                                                                      text_matching,
                                                                      href,
                                                                      href_matching,
                                                                      url,
                                                                      url_matching,
                                                                  })
                                                              ),
                                                          }),
                                                    after: '-24h',
                                                },
                                                full: true,
                                                showEventFilter: false,
                                                showPropertyFilter: false,
                                            }}
                                        />
                                    ),
                            },
                        ]}
                    />
                </>
            )}
        </SceneContent>
    )
}

const REFERENCES_COLUMNS: LemonTableColumns<ActionReference> = [
    {
        title: 'Name',
        dataIndex: 'name',
        render: function RenderName(_, ref) {
            return <LemonTableLink title={ref.name} to={ref.url} />
        },
    },
    {
        title: 'Type',
        dataIndex: 'type',
        render: function RenderType(_, ref) {
            return REFERENCE_TYPE_LABELS[ref.type] ?? ref.type
        },
    },
    {
        title: 'Created by',
        dataIndex: 'created_by',
        render: function RenderCreatedBy(_, ref) {
            if (!ref.created_by) {
                return <span className="text-muted">Unknown</span>
            }
            return (
                <div className="flex items-center gap-2">
                    <ProfilePicture user={ref.created_by} size="sm" />
                    <span>{ref.created_by.first_name || ref.created_by.email}</span>
                </div>
            )
        },
    },
    createdAtColumn() as LemonTableColumns<ActionReference>[number],
]

function ReferencesList({ logicProps }: { logicProps: ActionEditLogicProps }): JSX.Element {
    const { filteredReferences, referencesSearch } = useValues(actionEditLogic(logicProps))
    const { setReferencesSearch } = useActions(actionEditLogic(logicProps))

    return (
        <div className="flex flex-col gap-4">
            <LemonInput type="search" placeholder="Search..." value={referencesSearch} onChange={setReferencesSearch} />
            <LemonTable dataSource={filteredReferences} columns={REFERENCES_COLUMNS} pagination={{ pageSize: 10 }} />
        </div>
    )
}
