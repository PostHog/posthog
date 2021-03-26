import { Tag, Select } from 'antd'
import { colorForString } from 'lib/utils'
import React, { CSSProperties, useEffect, useRef, useState } from 'react'
import { PlusOutlined, SyncOutlined, CloseOutlined } from '@ant-design/icons'
import { SelectGradientOverflow } from '../SelectGradientOverflow'
import { RefSelectProps } from 'antd/lib/select'

interface ObjectTagsInterface {
    tags: string[]
    onTagSave?: (tag: string) => void
    onTagDelete?: (tag: string) => void
    tagsAvailable?: string[] // list of all tags that already exist
    saving?: boolean
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
    onTagSave, // Required unless `staticOnly`
    onTagDelete, // Required unless `staticOnly`
    saving, // Required unless `staticOnly`
    tagsAvailable,
    style,
    staticOnly,
}: ObjectTagsInterface): JSX.Element {
    const [addingNewTag, setAddingNewTag] = useState(false)
    const [newTag, setNewTag] = useState('')
    const [deletedTags, setDeletedTags] = useState<string[]>([]) // we use this state var to remove items immediately from UI while API requests are processed

    const handleDelete = (tag: string): void => {
        setDeletedTags([...deletedTags, tag])
        onTagDelete && onTagDelete(tag)
    }

    const addInput = useRef<RefSelectProps | null>(null)

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
                            onTagDelete &&
                            (deletedTags.includes(tag) ? (
                                <SyncOutlined spin />
                            ) : (
                                <CloseOutlined style={{ cursor: 'pointer' }} onClick={() => handleDelete(tag)} />
                            ))}
                    </Tag>
                )
            })}
            {!staticOnly && onTagSave && saving !== undefined && (
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
                    {addingNewTag && (
                        <SelectGradientOverflow
                            size="small"
                            onBlur={() => setAddingNewTag(false)}
                            //ref={addInput}
                            autoFocus
                            allowClear
                            autoClearSearchValue
                            defaultOpen
                            showSearch
                            style={{ width: 160 }}
                            onChange={(value) => {
                                onTagSave(value)
                            }}
                            disabled={saving}
                            loading={saving}
                            onSearch={(newInput) => {
                                setNewTag(newInput)
                            }}
                            placeholder='try "official"'
                        >
                            {newTag ? (
                                <Select.Option key={newTag} value={newTag} className="ph-no-capture">
                                    New Tag: {newTag}
                                </Select.Option>
                            ) : (
                                (!tagsAvailable || !tagsAvailable.length) && (
                                    <Select.Option key="__" value="__" disabled style={{ color: 'var(--muted)' }}>
                                        Enter your first tag
                                    </Select.Option>
                                )
                            )}
                            {tagsAvailable &&
                                tagsAvailable.map((tag) => (
                                    <Select.Option key={tag} value={tag} className="ph-no-capture">
                                        {tag}
                                    </Select.Option>
                                ))}
                        </SelectGradientOverflow>
                    )}
                </span>
            )}
        </div>
    )
}
