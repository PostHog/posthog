import React, { useEffect, useRef, useState } from 'react'
import { Button, Input } from 'antd'
import { DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import { SavedFilter, sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { useActions } from 'kea'

interface Props {
    filter: SavedFilter | { id: null }
}

export function SaveFilter({ filter }: Props): JSX.Element {
    const [name, setName] = useState(filter.id !== null ? filter.name : '')
    const { upsertSessionsFilter, deleteSessionsFilter } = useActions(sessionsFiltersLogic)

    const inputRef = useRef<Input>(null)
    useEffect(() => {
        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.focus()
            }
        })
    })

    return (
        <div style={{ maxWidth: 350 }} className="mb">
            <form
                onSubmit={(e): void => {
                    e.preventDefault()
                    upsertSessionsFilter(filter.id, name)
                }}
            >
                <div className="mb">
                    <Input
                        ref={inputRef}
                        required
                        placeholder="Name your filter"
                        maxLength={24}
                        value={name}
                        data-attr="sessions-filter.name"
                        onChange={(e) => setName(e.target.value)}
                    />
                </div>
                <div className="mt space-between-items">
                    <Button
                        type="primary"
                        htmlType="submit"
                        disabled={name.length < 2}
                        data-attr="save-sessions-filter"
                        icon={<SaveOutlined />}
                    >
                        Save
                    </Button>

                    {filter.id !== null && (
                        <Button
                            danger
                            data-attr="delete-sessions-filter"
                            icon={<DeleteOutlined />}
                            onClick={() => deleteSessionsFilter(filter.id)}
                        >
                            Delete
                        </Button>
                    )}
                </div>
            </form>
        </div>
    )
}
