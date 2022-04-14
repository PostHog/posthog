import { Tag, Select } from 'antd'
import equal from 'fast-deep-equal'
import { colorForString } from 'lib/utils'
import React, { CSSProperties, useEffect, useMemo } from 'react'
import { PlusOutlined, SyncOutlined, CloseOutlined } from '@ant-design/icons'
import { SelectGradientOverflow } from '../SelectGradientOverflow'
import { useActions, useValues } from 'kea'
import { objectTagsLogic } from 'lib/components/ObjectTags/objectTagsLogic'
import { Tooltip } from 'lib/components/Tooltip'

interface ObjectTagsPropsBase {
    tags: string[]
    saving?: boolean
    style?: CSSProperties
    id?: string
    className?: string
    'data-attr'?: string
}

type ObjectTagsProps =
    | (ObjectTagsPropsBase & {
          /** Tags CAN'T be added or removed. */
          staticOnly: true
          onChange?: never
          tagsAvailable?: never
          paywall?: never
      })
    | (ObjectTagsPropsBase & {
          /** Tags CAN be added or removed.*/
          staticOnly?: false
          onChange?: (tag: string, tags?: string[], id?: string) => void
          /** List of all tags that already exist. */
          tagsAvailable?: string[] /** Whether this field should be gated behind a "paywall". */
          paywall?: boolean
      })

const COLOR_OVERRIDES: Record<string, string> = {
    official: 'green',
    approved: 'green',
    verified: 'green',
    deprecated: 'red',
}

let uniqueMemoizedIndex = 1

export function ObjectTags({
    tags,
    onChange, // Required unless `staticOnly`
    saving, // Required unless `staticOnly`
    tagsAvailable,
    style = {},
    staticOnly = false,
    id, // For pages that allow multiple object tags
    paywall = false,
    className,
    'data-attr': dataAttr,
}: ObjectTagsProps): JSX.Element {
    const objectTagId = useMemo(() => uniqueMemoizedIndex++, [])
    const logic = objectTagsLogic({ id: objectTagId, onChange, tags })
    const { addingNewTag, newTag, cleanedNewTag, deletedTags, tags: _tags } = useValues(logic)
    const { setAddingNewTag, setNewTag, handleDelete, handleAdd, setTags } = useActions(logic)

    // Necessary to keep logic updated with component props
    useEffect(() => {
        if (!equal(tags, _tags)) {
            setTags(tags)
        }
    }, [tags])

    /** Displaying nothing is confusing, so in case of empty static tags we use a dash as a placeholder */
    const showPlaceholder = staticOnly && !tags?.length
    if (showPlaceholder && !style.color) {
        style.color = 'var(--muted)'
    }

    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, ...style }} className={className} data-attr={dataAttr}>
            {paywall ? (
                <Tooltip
                    title={
                        paywall
                            ? "This field is part of PostHog's tagging collaboration set and requires a premium plan."
                            : undefined
                    }
                    placement="right"
                >
                    <span style={{ display: 'inline-flex', fontWeight: 400 }}>
                        <Tag
                            data-attr="button-add-tag"
                            style={{
                                borderStyle: 'dashed',
                                backgroundColor: '#ffffff',
                                display: 'initial',
                                opacity: 0.6,
                                cursor: 'not-allowed',
                            }}
                            icon={<PlusOutlined />}
                        >
                            Add tag
                        </Tag>
                    </span>
                </Tooltip>
            ) : (
                <>
                    {showPlaceholder
                        ? '—'
                        : tags
                              .filter((t) => !!t)
                              .map((tag, index) => {
                                  return (
                                      <Tag
                                          key={index}
                                          color={COLOR_OVERRIDES[tag] || colorForString(tag)}
                                          style={{ marginRight: 0 }}
                                      >
                                          {tag}{' '}
                                          {!staticOnly &&
                                              onChange &&
                                              (deletedTags.includes(tag) ? (
                                                  <SyncOutlined spin />
                                              ) : (
                                                  <CloseOutlined
                                                      className="click-outside-block"
                                                      style={{ cursor: 'pointer' }}
                                                      onClick={() => handleDelete(tag)}
                                                  />
                                              ))}
                                      </Tag>
                                  )
                              })}
                    {!staticOnly && onChange && saving !== undefined && (
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
                                icon={<PlusOutlined />}
                            >
                                Add tag
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
                                    onChange={handleAdd}
                                    loading={saving}
                                    onSearch={setNewTag}
                                    placeholder='try "official"'
                                >
                                    {newTag ? (
                                        <Select.Option
                                            key={`${newTag}_${id}`}
                                            value={newTag}
                                            className="ph-no-capture"
                                            data-attr="new-tag-option"
                                        >
                                            {cleanedNewTag}
                                        </Select.Option>
                                    ) : (
                                        (!tagsAvailable || !tagsAvailable.length) && (
                                            <Select.Option
                                                key="__"
                                                value="__"
                                                disabled
                                                style={{ color: 'var(--muted)' }}
                                            >
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
                </>
            )}
        </div>
    )
}
