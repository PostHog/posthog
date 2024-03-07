import './Definition.scss'

import { TZLabel } from '@posthog/apps-common'
import { LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router/lib/utils'
import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { getFilterLabel } from 'lib/taxonomy'
import { DefinitionEdit } from 'scenes/data-management/definition/DefinitionEdit'
import {
    definitionLogic,
    DefinitionLogicProps,
    DefinitionPageMode,
} from 'scenes/data-management/definition/definitionLogic'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { AvailableFeature, PropertyDefinition } from '~/types'

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
                                                        This definition will be recreated if the {singular} is ever seen
                                                        again in the event stream.
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
                    <LemonDivider className="my-6" />
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
                    <LemonDivider className="my-6" />
                    {isEvent && definition.id !== 'new' && (
                        <>
                            <EventDefinitionProperties definition={definition} />
                            <LemonDivider className="my-6" />
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
