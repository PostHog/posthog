import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconBadge, IconEye, IconHide, IconInfo } from '@posthog/icons'
import { LemonTag, LemonTagType, Spinner, Tooltip } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { DefinitionLogicProps, definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { EventDefinitionInsights } from 'scenes/data-management/events/EventDefinitionInsights'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { EventDefinitionSchema } from 'scenes/data-management/events/EventDefinitionSchema'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { getFilterLabel } from '~/taxonomy/helpers'
import {
    AvailableFeature,
    FilterLogicalOperator,
    PropertyDefinition,
    PropertyDefinitionVerificationStatus,
    ReplayTabs,
} from '~/types'

import { getEventDefinitionIcon, getPropertyDefinitionIcon } from '../events/DefinitionHeader'

export const scene: SceneExport<DefinitionLogicProps> = {
    component: DefinitionView,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
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

export function DefinitionView(props: DefinitionLogicProps): JSX.Element {
    const logic = definitionLogic(props)
    const {
        definition,
        definitionLoading,
        definitionMissing,
        hasTaxonomyFeatures,
        singular,
        isEvent,
        isProperty,
        metrics,
        metricsLoading,
    } = useValues(logic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const onGuardClick = (callback: () => void): void => {
        guardAvailableFeature(AvailableFeature.INGESTION_TAXONOMY, () => {
            callback()
        })
    }
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
        <SceneContent>
            <SceneTitleSection
                name={definition.name}
                resourceType={
                    isEvent
                        ? {
                              type: 'event definition',
                              forceIcon: getEventDefinitionIcon(definition),
                          }
                        : {
                              type: 'property definition',
                              forceIcon: getPropertyDefinitionIcon(definition),
                          }
                }
                actions={
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
                                size="small"
                                targetBlank
                            >
                                View recordings
                            </LemonButton>
                        )}
                        <LemonButton
                            data-attr="delete-definition"
                            type="secondary"
                            status="danger"
                            size="small"
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
                        <LemonButton
                            data-attr="edit-definition"
                            type="secondary"
                            size="small"
                            onClick={() => {
                                if (isProperty) {
                                    router.actions.push(urls.propertyDefinitionEdit(definition.id))
                                    return
                                }
                                return onGuardClick(() => {
                                    router.actions.push(urls.eventDefinitionEdit(definition.id))
                                })
                            }}
                        >
                            Edit
                        </LemonButton>
                    </>
                }
                forceBackTo={
                    isEvent
                        ? {
                              path: urls.eventDefinitions(),
                              name: 'Event definitions',
                              key: 'events',
                          }
                        : {
                              path: urls.propertyDefinitions(),
                              name: 'Property definitions',
                              key: 'properties',
                          }
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
                <div className="flex flex-wrap gap-2 items-center text-secondary">
                    <div>{isProperty ? 'Property' : 'Event'} name:</div>
                    <LemonTag className="font-mono">{definition.name}</LemonTag>
                </div>
            </div>

            <SceneDivider />

            <div className="flex flex-wrap">
                {isEvent && (
                    <div className="flex flex-col flex-1">
                        <h5>First seen</h5>
                        <b>{definition.created_at ? <TZLabel time={definition.created_at} /> : '-'}</b>
                    </div>
                )}
                {isEvent && (
                    <div className="flex flex-col flex-1">
                        <h5>Last seen</h5>
                        <b>{definition.last_seen_at ? <TZLabel time={definition.last_seen_at} /> : '-'}</b>
                    </div>
                )}
                {isEvent && (
                    <div className="flex flex-col flex-1">
                        <h5>
                            30 day queries{' '}
                            <Tooltip title="Number of times this event has been queried in the last 30 days">
                                <IconInfo />
                            </Tooltip>
                        </h5>
                        <b>
                            {metricsLoading ? (
                                <Spinner textColored />
                            ) : (
                                <>{metrics?.query_usage_30_day ? metrics.query_usage_30_day.toLocaleString() : '-'}</>
                            )}
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

            <SceneDivider />

            {isEvent && definition.id !== 'new' && (
                <>
                    <FlaggedFeature flag={FEATURE_FLAGS.SCHEMA_MANAGEMENT}>
                        <EventDefinitionSchema definition={definition} />
                        <SceneDivider />
                    </FlaggedFeature>
                    <EventDefinitionProperties definition={definition} />
                    <SceneDivider />
                    <EventDefinitionInsights definition={definition} />
                    <SceneDivider />
                    <SceneSection
                        title="Connected destinations"
                        description="Get notified via Slack, webhooks or more whenever this event is captured."
                    >
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
                    </SceneSection>

                    <SceneDivider />
                    <SceneSection
                        title="Matching events"
                        description="This is the list of recent events that match this definition."
                    >
                        <Query query={memoizedQuery} />
                    </SceneSection>
                </>
            )}
        </SceneContent>
    )
}
