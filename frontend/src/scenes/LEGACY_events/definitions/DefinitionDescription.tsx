import { Input } from 'antd'
import { useValues, useActions } from 'kea'
import React from 'react'
import { definitionDrawerLogic } from './definitionDrawerLogic'

export function DefinitionDescription(): JSX.Element {
    const { description } = useValues(definitionDrawerLogic)
    const { setDescription, saveAll } = useActions(definitionDrawerLogic)

    return (
        <>
            <div style={{ flexDirection: 'column', minWidth: 300 }}>
                <h4 className="l4">Description</h4>
                <Input.TextArea
                    style={{ minHeight: 108, marginBottom: 8 }}
                    placeholder="Add description"
                    value={description || ''}
                    onChange={(e) => {
                        setDescription(e.target.value)
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            saveAll()
                        }
                    }}
                />
            </div>
        </>
    )
}
