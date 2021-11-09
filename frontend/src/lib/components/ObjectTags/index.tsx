import { Tag, Select } from 'antd'
import { colorForString } from 'lib/utils'
import React, { CSSProperties, useEffect, useState } from 'react'
import { PlusOutlined, SyncOutlined, CloseOutlined } from '@ant-design/icons'
import { SelectGradientOverflow } from '../SelectGradientOverflow'

interface ObjectTagsInterface {
    tags: string[]
    onTagSave?: (tag: string, tags?: string[], id?: string) => void
    onTagDelete?: (tag: string, tags?: string[], id?: string) => void
    tagsAvailable?: string[] // list of all tags that already exist
    saving?: boolean
    style?: CSSProperties
    staticOnly?: boolean // whether tags can be added or removed
    id?: string
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
    id, // For pages that allow multiple object tags
}: ObjectTagsInterface): JSX.Element {
    const [addingNewTag, setAddingNewTag] = useState(false)
    const [newTag, setNewTag] = useState('')
    const [deletedTags, setDeletedTags] = useState<string[]>([]) // we use this state var to remove items immediately from UI while API requests are processed

    const handleDelete = (tag: string, currentTags?: string[], propertyId?: string): void => {
        setDeletedTags([...deletedTags, tag])
        onTagDelete && onTagDelete(tag, currentTags, propertyId)
    }

    useEffect(() => {
        if (!saving) {
            setAddingNewTag(false)
            setNewTag('')
        }
    }, [saving])

    return (
        <div style={style}>
            {tags
                .filter((t) => !!t)
                .map((tag, index) => {
                    return (
                        <Tag key={index} color={COLOR_OVERRIDES[tag] || colorForString(tag)} style={{ marginTop: 8 }}>
                            {tag}{' '}
                            {!staticOnly &&
                                onTagDelete &&
                                (deletedTags.includes(tag) ? (
                                    <SyncOutlined spin />
                                ) : (
                                    <CloseOutlined
                                        style={{ cursor: 'pointer' }}
                                        onClick={() => handleDelete(tag, tags, id)}
                                    />
                                ))}
                        </Tag>
                    )
                })}
            {!staticOnly && onTagSave && saving !== undefined && (
                <span style={{ display: 'inline-flex', fontWeight: 400 }}>
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
                            data-attr="new-tag-input"
                            autoFocus
                            allowClear
                            autoClearSearchValue
                            defaultOpen
                            showSearch
                            style={{ width: 160 }}
                            onChange={(value) => {
                                onTagSave(value, tags, id)
                                setNewTag('')
                                setAddingNewTag(false)
                            }}
                            disabled={saving}
                            loading={saving}
                            onSearch={(newInput) => {
                                setNewTag(newInput)
                            }}
                            placeholder='try "official"'
                        >
                            {newTag ? (
                                <Select.Option
                                    key={`${newTag}_${id}`}
                                    value={newTag}
                                    className="ph-no-capture"
                                    data-attr="new-tag-option"
                                >
                                    New Tag: {newTag}
                                </Select.Option>
                            ) : (
                                (!tagsAvailable || !tagsAvailable.length) && (
                                    <Select.Option key="__" value="__" disabled style={{ color: 'var(--muted)' }}>
                                        Type to add a new tag
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
