import { BuiltLogic, Logic, LogicWrapper, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

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
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { getAccessControlDisabledReason, userHasAccess } from 'lib/utils/accessControlUtils'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
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
import type { ActionReferenceApi } from '../generated/api.schemas'
import {
    ActionEditLogicProps,
    DEFAULT_ACTION_STEP,
    REFERENCE_TYPE_LABELS,
    actionEditLogic,
} from '../logics/actionEditLogic'
import { actionLogic } from '../logics/actionLogic'

const RESOURCE_TYPE = 'action'

export interface ActionEditProps extends ActionEditLogicProps {
    actionLoading?: boolean
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
}

export function ActionEdit({ action: loadedAction, id, tabId, actionLoading, attachTo }: ActionEditProps): JSX.Element {
    const logicProps: ActionEditLogicProps = {
        id,
        action: loadedAction,
        tabId,
    }
    const { isComplete } = useValues(actionLogic)
    const logic = actionEditLogic(logicProps)
    // Attach to the scene-kept actionLogic so the form state persists across tab switches:
    // sceneLogic keeps actionLogic mounted per tab, and useAttachedLogic keeps actionEditLogic
    // alive for as long as actionLogic is mounted, even when this component unmounts.
    useAttachedLogic(logic, attachTo)
    const { action, actionChanged, isActionSubmitting } = useValues(logic)
    const { submitAction, deleteAction, setActionValue, setAction, setOriginalAction } = useActions(logic)

    // Sync the loaded action prop with the logic's internal state. This runs after load even
    // when the logic was mounted eagerly by useAttachedLogic (before the action has finished
    // loading), so the form and originalAction reducer both get populated once the data arrives.
    useEffect(() => {
        if (loadedAction && (!action || action.id !== loadedAction.id)) {
            setAction(loadedAction, { merge: false })
            setOriginalAction(loadedAction)
        }
    }, [loadedAction, action, setAction, setOriginalAction])
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
                                loading={isActionSubmitting}
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
                                disabledReason={
                                    isActionSubmitting ? 'Saving…' : !actionChanged ? 'No changes to save' : undefined
                                }
                            >
                                {actionChanged ? 'Save' : 'No changes'}
                            </LemonButton>
                        </>
                    }
                />

                <LemonCollapse
                    defaultActiveKey="match-groups"
                    panels={[
                        {
                            key: 'match-groups',
                            header: {
                                children: (
                                    <div className="py-1">
                                        <div className="font-semibold">Match groups</div>
                                        <div className="text-secondary text-sm font-normal">
                                            Your action will be triggered whenever <b>any of your match groups</b> are
                                            received.
                                        </div>
                                    </div>
                                ),
                            },
                            content: actionLoading ? (
                                <div className="flex gap-2">
                                    <LemonSkeleton className="w-1/2 h-[261px]" />
                                    <LemonSkeleton className="w-1/2 h-[261px]" />
                                </div>
                            ) : (
                                <LemonField name="steps">
                                    {({ value: stepsValue, onChange }) => (
                                        <div className="@container grid @4xl:grid-cols-2 gap-3">
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
                            ),
                        },
                    ]}
                />
            </Form>
            <ActionHogFunctions />
            {id && (
                <LemonCollapse
                    defaultActiveKey="used-in-analytics"
                    panels={[
                        {
                            key: 'used-in-analytics',
                            header: {
                                children: (
                                    <div className="py-1">
                                        <div className="font-semibold">Used in analytics</div>
                                        <div className="text-secondary text-sm font-normal">
                                            Insights, experiments, and cohorts that reference this action.
                                        </div>
                                    </div>
                                ),
                            },
                            content: <ReferencesList logicProps={logicProps} />,
                        },
                    ]}
                />
            )}
            {(id || action.steps?.length) && (
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
                            content: (
                                <MatchingEvents
                                    id={id}
                                    isComplete={isComplete}
                                    actionChanged={actionChanged}
                                    steps={action.steps}
                                />
                            ),
                        },
                    ]}
                />
            )}
        </SceneContent>
    )
}

const REFERENCES_COLUMNS: LemonTableColumns<ActionReferenceApi> = [
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
    createdByColumn() as LemonTableColumns<ActionReferenceApi>[number],
    createdAtColumn() as LemonTableColumns<ActionReferenceApi>[number],
]

function MatchingEvents({
    id,
    isComplete,
    actionChanged,
    steps,
}: {
    id?: number
    isComplete: boolean
    actionChanged: boolean
    steps?: ActionStepType[]
}): JSX.Element {
    const { filterTestAccountsDefault } = useValues(filterTestAccountsDefaultsLogic)

    const query = useMemo(() => {
        const source: Record<string, any> = {
            kind: NodeKind.EventsQuery,
            select: defaultDataTableColumns(NodeKind.EventsQuery),
            after: '-24h',
            filterTestAccounts: filterTestAccountsDefault,
        }
        if (id && !actionChanged) {
            source.actionId = id
        } else {
            source.actionSteps = steps?.map(
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
            )
        }
        return {
            kind: NodeKind.DataTableNode as const,
            source,
            full: true,
            showEventFilter: false,
            showPropertyFilter: false,
        }
    }, [id, actionChanged, steps, filterTestAccountsDefault])

    if (id && !isComplete && !actionChanged) {
        return (
            <div className="flex items-center">
                <Spinner className="mr-4" />
                Calculating action, please hold on...
            </div>
        )
    }

    return <Query query={query} />
}

function ReferencesList({ logicProps }: { logicProps: ActionEditLogicProps }): JSX.Element {
    const { filteredReferences, referencesSearch, referencesLoading } = useValues(actionEditLogic(logicProps))
    const { setReferencesSearch } = useActions(actionEditLogic(logicProps))

    return (
        <div className="flex flex-col gap-4">
            <LemonInput type="search" placeholder="Search..." value={referencesSearch} onChange={setReferencesSearch} />
            <LemonTable
                dataSource={filteredReferences}
                columns={REFERENCES_COLUMNS}
                pagination={{ pageSize: 10 }}
                loading={referencesLoading}
            />
        </div>
    )
}
