import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { EventDefinition } from '~/types'

import { PropertyGroupModal } from '../schema/PropertyGroupModal'
import { SelectPropertyGroupModal } from '../schema/SelectPropertyGroupModal'
import { SchemaPropertyGroupProperty, schemaManagementLogic } from '../schema/schemaManagementLogic'
import { EventSchema, eventDefinitionSchemaLogic } from './eventDefinitionSchemaLogic'

function PropertyRow({ property }: { property: SchemaPropertyGroupProperty }): JSX.Element {
    return (
        <div className="flex items-center gap-4 py-3 px-4 border-b last:border-b-0 bg-white">
            <div className="flex-1">
                <span className="font-semibold">{property.name}</span>
            </div>
            <div className="w-32">
                <LemonTag type="muted">{property.property_type}</LemonTag>
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

export function EventDefinitionSchema({ definition }: { definition: EventDefinition }): JSX.Element {
    const logic = eventDefinitionSchemaLogic({ eventDefinitionId: definition.id })
    const { eventSchemas, allPropertyGroups, eventSchemasLoading } = useValues(logic)
    const { addPropertyGroup, removePropertyGroup, loadAllPropertyGroups, loadEventSchemas } = useActions(logic)
    const [isModalOpen, setIsModalOpen] = useState(false)

    const schemaLogic = schemaManagementLogic({ key: `event-${definition.id}` })
    const { setPropertyGroupModalOpen, setEditingPropertyGroup } = useActions(schemaLogic)

    const selectedPropertyGroupIds = new Set(eventSchemas.map((schema: EventSchema) => schema.property_group.id))

    const handleAfterPropertyGroupSave = (): void => {
        loadEventSchemas()
        loadAllPropertyGroups()
    }

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
                    availablePropertyGroups={allPropertyGroups}
                    selectedPropertyGroupIds={selectedPropertyGroupIds}
                    onPropertyGroupCreated={() => {
                        // Reload property groups when a new one is created
                        loadAllPropertyGroups()
                    }}
                />

                {eventSchemas.length > 0 ? (
                    <div className="space-y-4">
                        {eventSchemas.map((schema: EventSchema) => (
                            <div key={schema.id} className="border rounded overflow-hidden">
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
                                            onClick={() => {
                                                setEditingPropertyGroup(schema.property_group)
                                                setPropertyGroupModalOpen(true)
                                            }}
                                            tooltip="Edit this property group"
                                        />
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            status="danger"
                                            onClick={() => removePropertyGroup(schema.id)}
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
                                        {schema.property_group.properties.map(
                                            (property: SchemaPropertyGroupProperty) => (
                                                <PropertyRow key={property.id} property={property} />
                                            )
                                        )}
                                    </>
                                )}
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="text-center text-muted py-8 border rounded bg-bg-light">
                        No property groups added yet. Add a property group above to define the schema for this event.
                    </div>
                )}
            </div>

            <PropertyGroupModal logicKey={`event-${definition.id}`} onAfterSave={handleAfterPropertyGroupSave} />
        </SceneSection>
    )
}
