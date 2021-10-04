import { Input, Row, Table } from 'antd'
import { useValues, useActions } from 'kea'
import { ObjectTags } from 'lib/components/ObjectTags'
import React, { useState } from 'react'
import { useDebouncedCallback } from 'use-debounce/lib'
import { PropertyDefinition } from '~/types'
import { definitionDrawerLogic } from './definitionDrawerLogic'

export function EventPropertiesStats(): JSX.Element {
    const { eventPropertiesDefinitions, eventsSnippet, eventPropertiesDefinitionTags, tagLoading } =
        useValues(definitionDrawerLogic)
    const { setNewEventPropertyTag, deleteEventPropertyTag, setEventPropertyDescription, saveAll } =
        useActions(definitionDrawerLogic)
    const propertyExamples = eventsSnippet[0]?.properties
    const tableColumns = [
        {
            title: 'Property',
            key: 'property',
            render: function renderProperty({ name }: PropertyDefinition) {
                return <span className="text-default">{name}</span>
            },
        },
        {
            title: 'Description',
            key: 'description',
            render: function renderDescription({ description, id }: PropertyDefinition) {
                const [newDescription, setNewDescription] = useState(description)
                const debouncePropertyDescription = useDebouncedCallback((value) => {
                    setEventPropertyDescription(value, id)
                }, 200)

                return (
                    <Input.TextArea
                        placeholder="Add description"
                        value={newDescription || ''}
                        onChange={(e) => {
                            setNewDescription(e.target.value)
                            debouncePropertyDescription(e.target.value)
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                saveAll()
                            }
                        }}
                    />
                )
            },
        },
        {
            title: 'Tags',
            key: 'tags',
            render: function renderTags({ id, tags }: PropertyDefinition) {
                return (
                    <ObjectTags
                        id={id}
                        tags={tags || []}
                        onTagSave={(tag, currentTags, propertyId) =>
                            setNewEventPropertyTag(tag, currentTags, propertyId)
                        }
                        onTagDelete={(tag, currentTags, propertyId) =>
                            deleteEventPropertyTag(tag, currentTags, propertyId)
                        }
                        saving={tagLoading}
                        tagsAvailable={eventPropertiesDefinitionTags?.filter((tag) => !tags?.includes(tag))}
                    />
                )
            },
        },
        {
            title: 'Example',
            key: 'example',
            render: function renderExample({ name }: PropertyDefinition) {
                let example = propertyExamples[name]
                // Just show a json stringify if it's an array or object
                example =
                    Array.isArray(example) || example instanceof Object
                        ? JSON.stringify(example).substr(0, 140)
                        : example
                return (
                    <div style={{ backgroundColor: '#F0F0F0', padding: '4px, 15px', textAlign: 'center' }}>
                        <span style={{ fontSize: 10, fontWeight: 400, fontFamily: 'monaco' }}>{example}</span>
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
                dataSource={eventPropertiesDefinitions}
                columns={tableColumns}
                rowKey={(row) => row.id}
                size="small"
                tableLayout="fixed"
                pagination={{ pageSize: 5, hideOnSinglePage: true }}
            />
        </>
    )
}
