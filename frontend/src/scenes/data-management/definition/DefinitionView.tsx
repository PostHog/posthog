import { IconBadge, IconEye } from '@posthog/icons'
import { IconHide } from '@posthog/icons'
import { LemonDivider, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { useMemo } from 'react'
import { definitionLogic, DefinitionLogicProps } from 'scenes/data-management/definition/definitionLogic'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { getFilterLabel } from '~/taxonomy/helpers'
import { FilterLogicalOperator, PropertyDefinition, PropertyDefinitionVerificationStatus, ReplayTabs } from '~/types'

export const scene: SceneExport = {
    component: DefinitionView,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }): (typeof definitionLogic)['props'] => ({
        id,
    }),
}

type StatusProps = {
    tagType: LemonTagType
    label: string
    icon: React.ReactNode
    tooltip: string
}

const getStatusProps = (isProperty: boolean): Record<PropertyDefinitionVerificationStatus, StatusProps> => ({
    verified: {
        tagType: 'success',
        label: 'Verified',
        icon: <IconBadge />,
        tooltip: `This ${
            isProperty ? 'property' : 'event'
        } is verified and can be used in filters and other selection components.`,
    },
    hidden: {
        tagType: 'danger',
        label: 'Hidden',
        icon: <IconHide />,
        tooltip: `This ${
            isProperty ? 'property' : 'event'
        } is hidden and will not appear in filters and other selection components.`,
    },
    visible: {
        tagType: 'default',
        label: 'Visible',
        icon: <IconEye />,
        tooltip: `This ${
            isProperty ? 'property' : 'event'
        } is visible and can be used in filters and other selection components.`,
    },
})

export function DefinitionView(props: DefinitionLogicProps = {}): JSX.Element {
    const logic = definitionLogic(props)
    const { definition, definitionLoading, definitionMissing, hasTaxonomyFeatures, singular, isEvent, isProperty } =
        useValues(logic)
    const { deleteDefinition } = useActions(logic)

    const memoizedQuery = useMemo(() => {
        const columnsToUse =
            'default_columns' in definition && !!definition.default_columns?.length
                ? definition.default_columns
                : defaultDataTableColumns(NodeKind.EventsQuery)

        return {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: columnsToUse,
                event: definition.name,
            },
            full: true,
            showEventFilter: false,
            showPersistentColumnConfigurator: true,
            context: {
                type: 'event_definition',
                eventDefinitionId: definition.id,
            },
        }
    }, [definition])

    if (definitionLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    if (definitionMissing) {
        return <NotFound object="event" />
    }

    const definitionStatus = definition.verified ? 'verified' : definition.hidden ? 'hidden' : 'visible'

    const statusProps = getStatusProps(isProperty)

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        {isEvent && (
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
                                                will no longer appear in selectors. Associated data will remain in the
                                                database.
                                            </p>
                                            <p>
                                                This definition will be recreated if the ${singular} is ever seen again
                                                in the event stream.
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

            <div className="deprecated-space-y-2">
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
                <div className="flex flex-wrap gap-2 items-center text-secondary-foreground">
                    <div>{isProperty ? 'Property' : 'Event'} name:</div>
                    <LemonTag className="font-mono">{definition.name}</LemonTag>
                </div>
            </div>

            <LemonDivider className="my-6" />
            <div className="flex flex-wrap">
                {isEvent && definition.created_at && (
                    <div className="flex flex-col flex-1">
                        <h5>First seen</h5>
                        <b>
                            <TZLabel time={definition.created_at} />
                        </b>
                    </div>
                )}
                {isEvent && definition.last_seen_at && (
                    <div className="flex flex-col flex-1">
                        <h5>Last seen</h5>
                        <b>
                            <TZLabel time={definition.last_seen_at} />
                        </b>
                    </div>
                )}

                {definitionStatus && (
                    <div className="flex flex-col flex-1">
                        <h5>Verification status</h5>
                        <div>
                            <Tooltip title={statusProps[definitionStatus].tooltip}>
                                <LemonTag type={statusProps[definitionStatus].tagType}>
                                    {statusProps[definitionStatus].icon}
                                    {statusProps[definitionStatus].label}
                                </LemonTag>
                            </Tooltip>
                        </div>
                    </div>
                )}

                {isProperty && (
                    <div className="flex flex-col flex-1">
                        <h5>Property type</h5>
                        <b>{(definition as PropertyDefinition).property_type ?? '-'}</b>
                    </div>
                )}
            </div>

            <LemonDivider className="my-6" />

            {isEvent && definition.id !== 'new' && (
                <>
                    <EventDefinitionProperties definition={definition} />

                    <LemonDivider className="my-6" />
                    <h2 className="flex-1 subtitle">Connected destinations</h2>
                    <p>Get notified via Slack, webhooks or more whenever this event is captured.</p>

                    <LinkedHogFunctions
                        type="destination"
                        forceFilterGroups={[
                            {
                                events: [
                                    {
                                        id: `${definition.name}`,
                                        type: 'events',
                                    },
                                ],
                            },
                        ]}
                    />
                    <LemonDivider className="my-6" />
                    <h3>Matching events</h3>
                    <p>This is the list of recent events that match this definition.</p>
                    <Query query={memoizedQuery} />
                </>
            )}
        </>
    )
}
