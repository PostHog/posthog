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
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { getPropertyLabel } from 'lib/taxonomy'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { NotFound } from 'lib/components/NotFound'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { combineUrl } from 'kea-router/lib/utils'
import { urls } from 'scenes/urls'
import { NodeKind } from '~/queries/schema'
import { Query } from '~/queries/Query/Query'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { TZLabel } from '@posthog/apps-common'

export const scene: SceneExport = {
    component: DefinitionView,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }): (typeof definitionLogic)['props'] => ({
        id,
    }),
}

export function DefinitionView(props: DefinitionLogicProps = {}): JSX.Element {
    const logic = definitionLogic(props)
    const {
        definition,
        definitionLoading,
        definitionMissing,
        hasTaxonomyFeatures,
        singular,
        mode,
        isEvent,
        isProperty,
    } = useValues(logic)
    const { setPageMode, deleteDefinition } = useActions(logic)
    const { hasAvailableFeature } = useValues(userLogic)

    if (definitionLoading) {
        return <SpinnerOverlay sceneLevel />
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
                                    markdown
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
                                    Raw {singular} name: <code>{definition.name}</code>
                                </div>
                            </>
                        }
                        buttons={
                            <>
                                {
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
                                                            <strong>{getPropertyLabel(definition.name)}</strong> will
                                                            no longer appear in selectors. Associated data will remain
                                                            in the database.
                                                        </p>
                                                        <p>
                                                            This definition will be recreated if the {singular} is ever
                                                            seen again in the event stream.
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
                                }
                                {isEvent && (
                                    <LemonButton
                                        type="secondary"
                                        to={
                                            combineUrl(urls.replay(), {
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

                                {(hasTaxonomyFeatures || isProperty) && (
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
                                    value={definition.created_at && <TZLabel time={definition.created_at} />}
                                />
                                <DefinitionPopover.Card
                                    title="Last seen"
                                    value={definition.last_seen_at && <TZLabel time={definition.last_seen_at} />}
                                />
                            </>
                        )}

                        {isProperty && (
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
                            </div>
                        </>
                    )}
                </>
            )}
        </div>
    )
}
