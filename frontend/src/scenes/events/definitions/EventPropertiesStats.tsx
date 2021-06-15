import { Input, Row, Table } from 'antd'
import { useValues, useActions } from 'kea'
import { ObjectTags } from 'lib/components/ObjectTags'
import React, { useState } from 'react'
import { useDebouncedCallback } from 'use-debounce/lib'
import { definitionDrawerLogic } from './definitionDrawerLogic'

export function EventPropertiesStats(): JSX.Element {
    const { eventProperties, eventsSnippet, propertyDefinitionTags, definitionLoading } = useValues(
        definitionDrawerLogic
    )
    const { saveNewPropertyTag, deletePropertyTag, setPropertyDescription } = useActions(definitionDrawerLogic)
    const propertyExamples = eventsSnippet[0]?.properties
    const tableColumns = [
        {
            title: 'Property',
            key: 'property',
            render: function renderProperty({ name }: { name: string }) {
                return <span className="text-default">{name}</span>
            },
        },
        {
            title: 'Description',
            key: 'description',
            render: function renderDescription({ description, id }: { description: string; id: string }) {
                const [newDescription, setNewDescription] = useState(description)
                const debouncePropertyDescription = useDebouncedCallback((value) => {
                    setPropertyDescription(value, id)
                }, 1000)

                return (
                    <Input.TextArea
                        placeholder="Add description"
                        value={newDescription || ''}
                        onChange={(e) => {
                            setNewDescription(e.target.value)
                            debouncePropertyDescription(e.target.value)
                        }}
                    />
                )
            },
        },
        {
            title: 'Tags',
            key: 'tags',
            render: function renderTags({ id, tags }: { id: string; tags: string[] }) {
                return (
                    <ObjectTags
                        id={id}
                        tags={tags || []}
                        onTagSave={(tag, currentTags, propertyId) => saveNewPropertyTag(tag, currentTags, propertyId)}
                        onTagDelete={(tag, currentTags, propertyId) => deletePropertyTag(tag, currentTags, propertyId)}
                        saving={definitionLoading}
                        tagsAvailable={propertyDefinitionTags.filter((tag) => !tags?.includes(tag))}
                    />
                )
            },
        },
        {
            title: 'Example',
            key: 'example',
            render: function renderExample({ name }: { name: string }) {
                return (
                    <div style={{ backgroundColor: '#F0F0F0', padding: '4px, 15px', textAlign: 'center' }}>
                        <span style={{ fontSize: 10, fontWeight: 400, fontFamily: 'monaco' }}>
                            {propertyExamples[name]}
                        </span>
                    </div>
                )
            },
        },
    ]

    return (
        <>
            <Row style={{ paddingBottom: 16 }}>
                <span className="text-default text-muted">
                    Top properties that are sent with this event. Please note that description and tags are shared
                    across events. Posthog properties are <b>excluded</b> from this list.
                </span>
            </Row>
            <Table
                dataSource={eventProperties}
                columns={tableColumns}
                rowKey={(row) => row.id}
                size="small"
                tableLayout="fixed"
                pagination={{ pageSize: 5, hideOnSinglePage: true }}
            />
        </>
    )
}
