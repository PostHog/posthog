import { Card, Input } from 'antd'
import React, { Ref, useState } from 'react'
import { EditOutlined } from '@ant-design/icons'
import { DashboardItemType, DashboardMode, ItemMode } from '~/types'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import './Description.scss'
import { TextAreaRef } from 'antd/lib/input/TextArea'

interface DescriptionInterface {
    item: Partial<DashboardItemType>
    itemMode: ItemMode | DashboardMode | null
    setItemMode:
        | ((mode: ItemMode | null, eventSource: DashboardEventSource) => void)
        | ((mode: DashboardMode | null, eventSource: DashboardEventSource) => void)
    triggerItemUpdate: (description: Partial<DashboardItemType>) => void
    descriptionInputRef: Ref<TextAreaRef> | undefined
}

export function Description({
    item,
    itemMode,
    setItemMode,
    triggerItemUpdate,
    descriptionInputRef,
}: DescriptionInterface): JSX.Element {
    const [newDescription, setNewDescription] = useState(item.description) // Used to update the input immediately, debouncing API calls

    return (
        <Card className="description" bordered={!(itemMode === ItemMode.Edit)}>
            {itemMode === ItemMode.Edit ? (
                <Input.TextArea
                    placeholder="Add a description that helps others understand it better."
                    value={newDescription}
                    onChange={(e) => {
                        setNewDescription(e.target.value) // To update the input immediately
                        triggerItemUpdate({ description: e.target.value }) // This is breakpointed (i.e. debounced) to avoid multiple API calls
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                            setItemMode(null, DashboardEventSource.InputEnter)
                        }
                    }}
                    ref={descriptionInputRef}
                    tabIndex={5}
                    allowClear
                />
            ) : (
                <div
                    className="edit-box"
                    onClick={() => setItemMode(ItemMode.Edit as any, DashboardEventSource.AddDescription)}
                >
                    {item.description ? (
                        <span>{item.description}</span>
                    ) : (
                        <span className="add-description">Add a description...</span>
                    )}
                    <EditOutlined />
                </div>
            )}
        </Card>
    )
}
