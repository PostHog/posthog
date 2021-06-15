import { Button, Input, Row } from 'antd'
import { useActions } from 'kea'
import React, { useState } from 'react'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

export function VolumeTableRecordDescription({ id, description }: { id: string; description: string }): JSX.Element {
    const { updateEventDescription } = useActions(eventDefinitionsModel)
    const [newDescription, setDescription] = useState(description)
    const [editing, setEditing] = useState(false)

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
                    // onBlur={() => setEditing(false)}
                    placeholder="Click to add description"
                    onChange={(e) => setDescription(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            setEditing(false)
                            updateEventDescription(id, newDescription)
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
                            updateEventDescription(id, newDescription)
                        }}
                    >
                        Save
                    </Button>
                </Row>
            )}
        </>
    )
}
