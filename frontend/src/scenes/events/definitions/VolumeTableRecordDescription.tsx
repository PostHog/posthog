import { Button, Input, Row } from 'antd'
import { useActions } from 'kea'
import React, { useEffect, useState } from 'react'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

export function VolumeTableRecordDescription({
    id,
    description,
    type,
}: {
    id: string
    description: string
    type: string
}): JSX.Element {
    const { updateDescription } = useActions(eventDefinitionsModel)
    const [newDescription, setDescription] = useState(description)
    const [editing, setEditing] = useState(false)

    useEffect(() => {
        setDescription(description)
    }, [description])

    return (
        <>
            <Row>
                <Input.TextArea
                    value={newDescription || ''}
                    style={{ paddingLeft: 0 }}
                    bordered={editing}
                    onClick={(e) => {
                        e.stopPropagation()
                        setEditing(true)
                    }}
                    placeholder="Click to add description"
                    onChange={(e) => setDescription(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            setEditing(false)
                            updateDescription(id, newDescription, type)
                        }
                    }}
                    autoSize
                />
            </Row>
            {editing && (
                <Row style={{ float: 'right', marginTop: 8 }}>
                    <Button
                        size="small"
                        style={{ marginRight: 8 }}
                        onClick={(e) => {
                            e.stopPropagation()
                            setEditing(false)
                            setDescription(description)
                        }}
                    >
                        Cancel
                    </Button>
                    <Button
                        type="primary"
                        size="small"
                        onClick={(e) => {
                            e.stopPropagation()
                            setDescription(newDescription)
                            setEditing(false)
                            updateDescription(id, newDescription, type)
                        }}
                    >
                        Save
                    </Button>
                </Row>
            )}
        </>
    )
}
