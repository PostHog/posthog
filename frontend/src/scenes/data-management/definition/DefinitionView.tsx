import './Definition.scss'
import clsx from 'clsx'
import { Divider } from 'antd'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { AvailableFeature, PropertyDefinition } from '~/types'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import {
    definitionLogic,
    DefinitionLogicProps,
    DefinitionPageMode,
} from 'scenes/data-management/definition/definitionLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DefinitionEdit } from 'scenes/data-management/definition/DefinitionEdit'
import { formatTimeFromNow } from 'lib/components/DefinitionPopover/utils'
import { humanFriendlyNumber } from 'lib/utils'
import {
    ThirtyDayQueryCountTitle,
    ThirtyDayVolumeTitle,
} from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { getPropertyLabel } from 'lib/components/PropertyKeyInfo'
import { EventsTable } from 'scenes/events'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { NotFound } from 'lib/components/NotFound'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { combineUrl } from 'kea-router/lib/utils'
import { urls } from 'scenes/urls'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { NodeKind } from '~/queries/schema'
import { Query } from '~/queries/Query/Query'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'

export const scene: SceneExport = {
    component: DefinitionView,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }): typeof definitionLogic['props'] => ({
        id,
    }),
}

export function DefinitionView(props: DefinitionLogicProps = {}): JSX.Element {
    const logic = definitionLogic(props)
    const {
        definition,
        definitionLoading,
        definitionMissing,
        singular,
        mode,
        isEvent,
        backDetailUrl,
        hasTaxonomyFeatures,
    } = useValues(logic)
    const { setPageMode } = useActions(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]

    if (definitionLoading) {
        return <SpinnerOverlay />
    }

    if (definitionMissing) {
        return <NotFound object="event" />
    }

    return (
        <div className={clsx('definition-page', `definition-${mode}-page`)}>
            {mode === DefinitionPageMode.Edit ? (
                <DefinitionEdit {...props} definition={definition} />
            ) : (
                <>
                    <PageHeader
                        title={
                            <EditableField
                                name="name"
                                value={getPropertyLabel(definition.name) || ''}
                                placeholder={`Name this ${singular}`}
                                mode="view"
                                minLength={1}
                                maxLength={400} // Sync with action model
                                data-attr="definition-name-view"
                            />
                        }
                        caption={
                            <>
                                <EditableField
                                    multiline
                                    name="description"
                                    value={definition.description || ''}
                                    placeholder="Description (optional)"
                                    mode="view"
                                    data-attr="definition-description-view"
                                    className="definition-description"
                                    compactButtons
                                    maxLength={600}
                                    paywall={!hasAvailableFeature(AvailableFeature.INGESTION_TAXONOMY)}
                                />
                                <ObjectTags
                                    tags={definition.tags ?? []}
                                    data-attr="definition-tags-view"
                                    className="definition-tags"
                                    saving={definitionLoading}
                                />
                                <DefinitionPopover.TimeMeta
                                    createdAt={
                                        (definition && 'created_at' in definition && definition.created_at) || undefined
                                    }
                                    updatedAt={
                                        (definition && 'updated_at' in definition && definition.updated_at) || undefined
                                    }
                                    updatedBy={
                                        (definition && 'updated_by' in definition && definition.updated_by) || undefined
                                    }
                                />
                                <div className="definition-sent-as">
                                    Raw {singular} name: <pre>{definition.name}</pre>
                                </div>
                            </>
                        }
                        buttons={
                            <>
                                {isEvent && (
                                    <LemonButton
                                        type="secondary"
                                        to={
                                            combineUrl(urls.sessionRecordings(), {
                                                filters: {
                                                    events: [
                                                        {
                                                            id: definition.name,
                                                            type: 'events',
                                                            order: 0,
                                                            name: definition.name,
                                                        },
                                                    ],
                                                },
                                            }).url
                                        }
                                        sideIcon={<IconPlayCircle />}
                                        data-attr="event-definition-view-recordings"
                                    >
                                        View recordings
                                    </LemonButton>
                                )}

                                {hasTaxonomyFeatures && (
                                    <LemonButton
                                        data-attr="edit-definition"
                                        type="secondary"
                                        onClick={() => {
                                            setPageMode(DefinitionPageMode.Edit)
                                        }}
                                    >
                                        Edit
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                    <Divider />
                    <DefinitionPopover.Grid cols={2}>
                        {isEvent && (
                            <>
                                <DefinitionPopover.Card
                                    title="First seen"
                                    value={formatTimeFromNow(definition.created_at)}
                                />
                                <DefinitionPopover.Card
                                    title="Last seen"
                                    value={formatTimeFromNow(definition.last_seen_at)}
                                />
                                <DefinitionPopover.Card
                                    title={<ThirtyDayVolumeTitle />}
                                    value={
                                        definition.volume_30_day == null
                                            ? '-'
                                            : humanFriendlyNumber(definition.volume_30_day)
                                    }
                                />
                            </>
                        )}

                        <DefinitionPopover.Card
                            title={<ThirtyDayQueryCountTitle />}
                            value={
                                definition.query_usage_30_day == null
                                    ? '-'
                                    : humanFriendlyNumber(definition.query_usage_30_day)
                            }
                        />
                        {!isEvent && (
                            <DefinitionPopover.Card
                                title="Property Type"
                                value={(definition as PropertyDefinition).property_type ?? '-'}
                            />
                        )}
                    </DefinitionPopover.Grid>
                    <Divider />
                    {isEvent && definition.id !== 'new' && (
                        <>
                            <EventDefinitionProperties definition={definition} />
                            <Divider />
                            <div className="definition-matching-events">
                                <span className="definition-matching-events-header">Matching events</span>
                                <p className="definition-matching-events-subtext">
                                    This is the list of recent events that match this definition.
                                </p>
                                <div className="pt-4 border-t" />
                                {featureDataExploration ? (
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
                                ) : (
                                    <EventsTable
                                        sceneUrl={backDetailUrl}
                                        pageKey={`definition-page-${definition.id}`}
                                        showEventFilter={false}
                                        fetchMonths={3}
                                        fixedFilters={{
                                            event_filter: definition.name,
                                        }}
                                    />
                                )}
                            </div>
                        </>
                    )}
                </>
            )}
        </div>
    )
}
