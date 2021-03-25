import { Input, Tag } from 'antd'
import { colorForString } from 'lib/utils'
import React, { CSSProperties, useEffect, useRef, useState } from 'react'
import { PlusOutlined, SyncOutlined, CloseOutlined } from '@ant-design/icons'

interface ObjectTagsInterface {
    tags: string[]
    onTagSave: (tag: string) => void
    onTagDelete: (tag: string) => void
    saving: boolean
    style?: CSSProperties
    staticOnly?: boolean // whether tags can be added or removed
}

const COLOR_OVERRIDES: Record<string, string> = {
    official: 'green',
    approved: 'green',
    verified: 'green',
    deprecated: 'red',
}

export function ObjectTags({
    tags,
    onTagSave,
    onTagDelete,
    saving,
    style,
    staticOnly,
}: ObjectTagsInterface): JSX.Element {
    const [addingNewTag, setAddingNewTag] = useState(false)
    const [newTag, setNewTag] = useState('')
    const [deletedTags, setDeletedTags] = useState<string[]>([]) // we use this state var to remove items immediately from UI while API requests are processed

    const handleDelete = (tag: string): void => {
        setDeletedTags([...deletedTags, tag])
        onTagDelete(tag)
    }

    const addInput = useRef<Input | null>(null)

    useEffect(() => {
        if (!saving) {
            setAddingNewTag(false)
            setNewTag('')
        }
    }, [saving])

    useEffect(() => {
        addingNewTag && addInput.current?.focus()
    }, [addingNewTag])

    return (
        <div style={style}>
            {tags.map((tag, index) => {
                return (
                    <Tag key={index} color={COLOR_OVERRIDES[tag] || colorForString(tag)}>
                        {tag}{' '}
                        {!staticOnly &&
                            (deletedTags.includes(tag) ? (
                                <SyncOutlined spin />
                            ) : (
                                <CloseOutlined style={{ cursor: 'pointer' }} onClick={() => handleDelete(tag)} />
                            ))}
                    </Tag>
                )
            })}
            {!staticOnly && (
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
                        ref={addInput}
                        style={{ width: 78, display: !addingNewTag ? 'none' : 'flex' }}
                        value={newTag}
                        onChange={(e) => setNewTag(e.target.value)}
                        onPressEnter={() => onTagSave(newTag)}
                        disabled={saving}
                        prefix={saving ? <SyncOutlined spin /> : null}
                        placeholder='try "official"'
                    />
                </span>
            )}
        </div>
    )
}
