import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconInfo, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { Query } from '~/queries/Query/Query'
import { urls } from '~/scenes/urls'
import { EventDefinition } from '~/types'

import { PropertyGroupModal } from '../schema/PropertyGroupModal'
import { PropertyTypeTag } from '../schema/PropertyTypeTag'
import { SelectPropertyGroupModal } from '../schema/SelectPropertyGroupModal'
import { SchemaPropertyGroupProperty, schemaManagementLogic } from '../schema/schemaManagementLogic'
import { EventSchema, eventDefinitionSchemaLogic } from './eventDefinitionSchemaLogic'
import { buildPropertyGroupTrendsQuery } from './propertyGroupTrendsQuery'

function PropertyRow({ property }: { property: SchemaPropertyGroupProperty }): JSX.Element {
    return (
        <div className="flex items-center gap-4 py-3 px-4 border-b last:border-b-0 bg-white">
            <div className="flex-1">
                <span className="font-semibold">{property.name}</span>
            </div>
            <div className="w-32">
                <PropertyTypeTag propertyName={property.name} schemaPropertyType={property.property_type} />
            </div>
            <div className="w-24">
                {property.is_required ? (
                    <LemonTag type="danger">Required</LemonTag>
                ) : (
                    <LemonTag type="muted">Optional</LemonTag>
                )}
            </div>
            <div className="flex-1 text-muted">{property.description || '—'}</div>
        </div>
    )
}

function PropertyGroupCard({
    schema,
    eventName,
    onEdit,
    onRemove,
}: {
    schema: EventSchema
    eventName: string
    onEdit: () => void
    onRemove: () => void
}): JSX.Element {
    const queryResult = useMemo(
        () => buildPropertyGroupTrendsQuery(eventName, schema.property_group.properties),
        [eventName, schema.property_group.properties]
    )

    const linkQuery = useMemo(
        () => ({
            ...queryResult.query,
            showHeader: true,
            showTable: true,
            showFilters: true,
            embedded: false,
        }),
        [queryResult.query]
    )

    const insightUrl = useMemo(() => urls.insightNew({ query: linkQuery }), [linkQuery])

    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center justify-between p-4 bg-bg-light border-b">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{schema.property_group.name}</span>
                    <LemonTag type="default">
                        {schema.property_group.properties?.length || 0}{' '}
                        {schema.property_group.properties?.length === 1 ? 'property' : 'properties'}
                    </LemonTag>
                </div>
                <div className="flex gap-1">
                    <LemonButton
                        icon={<IconPencil />}
                        size="small"
                        onClick={onEdit}
                        tooltip="Edit this property group"
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        status="danger"
                        onClick={onRemove}
                        tooltip="Remove this property group from the event schema"
                    />
                </div>
            </div>
            {schema.property_group.properties && schema.property_group.properties.length > 0 && (
                <>
                    <div className="flex gap-4 py-2 px-4 bg-accent-3000 border-b text-xs font-semibold uppercase tracking-wider">
                        <div className="flex-1">Property</div>
                        <div className="w-32">Type</div>
                        <div className="w-24">Required</div>
                        <div className="flex-1">Description</div>
                    </div>
                    {schema.property_group.properties.map((property: SchemaPropertyGroupProperty) => (
                        <PropertyRow key={property.id} property={property} />
                    ))}
                    <div className="p-4 bg-bg-light">
                        <h4 className="font-semibold mb-2 text-sm flex items-center gap-1">
                            <Link to={insightUrl} className="text-default hover:text-link">
                                Property Coverage Trends (90 days)
                            </Link>
                            <Tooltip title="% of events containing this property">
                                <IconInfo className="text-xl text-secondary shrink-0" />
                            </Tooltip>
                        </h4>
                        {queryResult.isTruncated && (
                            <div className="mb-2 px-2 py-1 bg-warning-highlight text-warning text-xs rounded">
                                Only showing {queryResult.displayedProperties} of {queryResult.totalProperties}{' '}
                                properties. Chart is limited to 25 properties.
                            </div>
                        )}
                        <div>
                            <Query query={queryResult.query} readOnly embedded />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

export function EventDefinitionSchema({ definition }: { definition: EventDefinition }): JSX.Element {
    const logic = eventDefinitionSchemaLogic({ eventDefinitionId: definition.id })
    const { eventSchemas, eventSchemasLoading } = useValues(logic)
    const { addPropertyGroup, removePropertyGroup, loadAllPropertyGroups } = useActions(logic)
    const [isModalOpen, setIsModalOpen] = useState(false)

    const schemaLogic = schemaManagementLogic({ key: `event-${definition.id}` })
    const { setPropertyGroupModalOpen, setEditingPropertyGroup } = useActions(schemaLogic)

    const selectedPropertyGroupIds = useMemo<Set<string>>(
        () => new Set(eventSchemas.map((schema: EventSchema) => schema.property_group.id)),
        [eventSchemas]
    )

    return (
        <SceneSection
            title="Schema"
            description="Define which property groups this event should have. Property groups establish a schema that helps document expected properties."
            actions={
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={() => setIsModalOpen(true)}
                    disabled={eventSchemasLoading}
                >
                    Add Property Group
                </LemonButton>
            }
        >
            <div className="space-y-4">
                <SelectPropertyGroupModal
                    isOpen={isModalOpen}
                    onClose={() => setIsModalOpen(false)}
                    onSelect={(propertyGroupId) => addPropertyGroup(propertyGroupId)}
                    selectedPropertyGroupIds={selectedPropertyGroupIds}
                    onPropertyGroupCreated={() => {
                        loadAllPropertyGroups()
                    }}
                />

                {eventSchemas.length > 0 ? (
                    <div className="space-y-4">
                        {eventSchemas.map((schema: EventSchema) => (
                            <PropertyGroupCard
                                key={schema.id}
                                schema={schema}
                                eventName={definition.name}
                                onEdit={() => {
                                    setEditingPropertyGroup(schema.property_group)
                                    setPropertyGroupModalOpen(true)
                                }}
                                onRemove={() => removePropertyGroup(schema.id)}
                            />
                        ))}
                    </div>
                ) : (
                    <div className="text-center text-muted py-8 border rounded bg-bg-light">
                        No property groups added yet. Add a property group above to define the schema for this event.
                    </div>
                )}
            </div>

            <PropertyGroupModal logicKey={`event-${definition.id}`} />
        </SceneSection>
    )
}
