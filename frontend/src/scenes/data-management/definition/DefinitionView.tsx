import { TZLabel } from '@posthog/apps-common'
import { LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { getFilterLabel } from 'lib/taxonomy'
import { definitionLogic, DefinitionLogicProps } from 'scenes/data-management/definition/definitionLogic'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { FilterLogicalOperator, PropertyDefinition, ReplayTabs } from '~/types'

export const scene: SceneExport = {
    component: DefinitionView,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }): (typeof definitionLogic)['props'] => ({
        id,
    }),
}

export function DefinitionView(props: DefinitionLogicProps = {}): JSX.Element {
    const logic = definitionLogic(props)
    const { definition, definitionLoading, definitionMissing, hasTaxonomyFeatures, singular, isEvent, isProperty } =
        useValues(logic)
    const { deleteDefinition } = useActions(logic)
    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')

    if (definitionLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    if (definitionMissing) {
        return <NotFound object="event" />
    }

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        {isEvent && (
                            <LemonButton
                                type="secondary"
                                to={urls.replay(ReplayTabs.Recent, {
                                    filter_group: {
                                        type: FilterLogicalOperator.And,
                                        values: [
                                            {
                                                type: FilterLogicalOperator.And,
                                                values: [
                                                    {
                                                        id: definition.name,
                                                        type: 'events',
                                                        order: 0,
                                                        name: definition.name,
                                                    },
                                                ],
                                            },
                                        ],
                                    },
                                })}
                                sideIcon={<IconPlayCircle />}
                                data-attr="event-definition-view-recordings"
                            >
                                View recordings
                            </LemonButton>
                        )}
                        <LemonButton
                            data-attr="delete-definition"
                            type="secondary"
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Delete this ${singular} definition?`,
                                    description: (
                                        <>
                                            <p>
                                                <strong>
                                                    {getFilterLabel(
                                                        definition.name,
                                                        isEvent
                                                            ? TaxonomicFilterGroupType.Events
                                                            : TaxonomicFilterGroupType.EventProperties
                                                    )}
                                                </strong>{' '}
                                                will no longer appear in selectors. Associated data will remain
                                                in the database.
                                            </p>
                                            <p>
                                                This definition will be recreated if the {singular} is ever seen again
                                                in the event stream.
                                            </p>
                                        </>
                                    ),
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Delete definition',
                                        onClick: () => deleteDefinition(),
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                    width: 448,
                                })
                            }
                            tooltip="Delete this definition. Associated data will remain."
                        >
                            Delete
                        </LemonButton>
                        {(hasTaxonomyFeatures || isProperty) && (
                            <LemonButton
                                data-attr="edit-definition"
                                type="secondary"
                                to={
                                    isEvent
                                        ? urls.eventDefinitionEdit(definition.id)
                                        : urls.propertyDefinitionEdit(definition.id)
                                }
                            >
                                Edit
                            </LemonButton>
                        )}
                    </>
                }
            />

            <div className="space-y-2">
                {definition.description || isProperty || hasTaxonomyFeatures ? (
                    <EditableField
                        multiline
                        name="description"
                        markdown
                        value={definition.description || ''}
                        placeholder="Description (optional)"
                        mode="view"
                        data-attr="definition-description-view"
                        className="definition-description"
                        compactButtons
                        maxLength={600}
                    />
                ) : null}
                <ObjectTags
                    tags={definition.tags ?? []}
                    data-attr="definition-tags-view"
                    className="definition-tags"
                    saving={definitionLoading}
                />

                <UserActivityIndicator at={definition.updated_at} by={definition.updated_by} />
                <div className="flex flex-wrap items-center gap-2 text-muted-alt">
                    <div>Raw event name:</div>
                    <LemonTag className="font-mono">{definition.name}</LemonTag>
                </div>
            </div>

            <LemonDivider className="my-6" />
            <div className="flex flex-wrap">
                {isEvent && definition.created_at && (
                    <div className="flex-1 flex flex-col">
                        <h5>First seen</h5>
                        <b>
                            <TZLabel time={definition.created_at} />
                        </b>
                    </div>
                )}
                {isEvent && definition.last_seen_at && (
                    <div className="flex-1 flex flex-col">
                        <h5>Last seen</h5>
                        <b>
                            <TZLabel time={definition.last_seen_at} />
                        </b>
                    </div>
                )}

                {isProperty && (
                    <div className="flex-1 flex flex-col">
                        <h5>Property type</h5>
                        <b>{(definition as PropertyDefinition).property_type ?? '-'}</b>
                    </div>
                )}
            </div>

            <LemonDivider className="my-6" />

            {isEvent && definition.id !== 'new' && (
                <>
                    <EventDefinitionProperties definition={definition} />

                    {hogFunctionsEnabled && (
                        <>
                            <LemonDivider className="my-6" />
                            <h2 className="flex-1 subtitle">Connected destinations</h2>
                            <p>Get notified via Slack, webhooks or more whenever this event is captured.</p>

                            <LinkedHogFunctions
                                filters={{
                                    events: [
                                        {
                                            id: `${definition.name}`,
                                            type: 'events',
                                        },
                                    ],
                                }}
                            />
                        </>
                    )}
                    <LemonDivider className="my-6" />
                    <h3>Matching events</h3>
                    <p>This is the list of recent events that match this definition.</p>
                    <Query
                        query={{
                            kind: NodeKind.DataTableNode,
                            source: {
                                kind: NodeKind.EventsQuery,
                                select: defaultDataTableColumns(NodeKind.EventsQuery),
                                event: definition.name,
                            },
                            full: true,
                            showEventFilter: false,
                        }}
                    />
                </>
            )}
        </>
    )
}
