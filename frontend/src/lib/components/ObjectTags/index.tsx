import { Input, Tag } from 'antd'
import { colorForString } from 'lib/utils'
import React, { CSSProperties, useEffect, useState } from 'react'
import { PlusOutlined, SyncOutlined, CloseOutlined } from '@ant-design/icons'

interface ObjectTagsInterface {
    tags: string[]
    onTagSave: (tag: string) => void
    onTagDelete: (tag: string) => void
    saving: boolean
    style?: CSSProperties
    disabledChanges?: boolean
}

export function ObjectTags({
    tags,
    onTagSave,
    onTagDelete,
    saving,
    style,
    disabledChanges,
}: ObjectTagsInterface): JSX.Element {
    const [addingNewTag, setAddingNewTag] = useState(false)
    const [newTag, setNewTag] = useState('')
    const [deletedTags, setDeletedTags] = useState<string[]>([]) // we use this state var to remove items immediately from UI while API requests are processed

    const handleDelete = (tag: string): void => {
        setDeletedTags([...deletedTags, tag])
        onTagDelete(tag)
    }

    useEffect(() => {
        if (!saving) {
            setAddingNewTag(false)
            setNewTag('')
        }
    }, [saving])

    return (
        <div style={style}>
            {tags.map((tag, index) => {
                return (
                    <Tag key={index} color={colorForString(tag)}>
                        {tag}{' '}
                        {!disabledChanges &&
                            (deletedTags.includes(tag) ? (
                                <SyncOutlined spin />
                            ) : (
                                <CloseOutlined style={{ cursor: 'pointer' }} onClick={() => handleDelete(tag)} />
                            ))}
                    </Tag>
                )
            })}
            {!disabledChanges && (
                <span style={{ display: 'inline-flex' }}>
                    <Tag
                        onClick={() => setAddingNewTag(true)}
                        data-attr="button-add-tag"
                        style={{
                            cursor: 'pointer',
                            borderStyle: 'dashed',
                            backgroundColor: '#ffffff',
                            display: addingNewTag ? 'none' : 'initial',
                        }}
                    >
                        <PlusOutlined /> New Tag
                    </Tag>
                    <Input
                        type="text"
                        size="small"
                        onBlur={() => setAddingNewTag(false)}
                        //ref={addTagInput}
                        style={{ width: 78, display: !addingNewTag ? 'none' : 'flex' }}
                        value={newTag}
                        onChange={(e) => setNewTag(e.target.value)}
                        onPressEnter={() => onTagSave(newTag)}
                        disabled={saving}
                        prefix={saving ? <SyncOutlined spin /> : null}
                        placeholder="new-tag"
                    />
                </span>
            )}
        </div>
    )
}
