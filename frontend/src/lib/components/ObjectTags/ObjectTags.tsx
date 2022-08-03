import { Tag, Select } from 'antd'
import { colorForString } from 'lib/utils'
import React, { CSSProperties, useMemo } from 'react'
import { PlusOutlined, SyncOutlined, CloseOutlined } from '@ant-design/icons'
import { SelectGradientOverflow } from '../SelectGradientOverflow'
import { useActions, useValues } from 'kea'
import { objectTagsLogic } from 'lib/components/ObjectTags/objectTagsLogic'
import { AvailableFeature } from '~/types'
import { sceneLogic } from 'scenes/sceneLogic'

interface ObjectTagsPropsBase {
    tags: string[]
    saving?: boolean
    style?: CSSProperties
    id?: string
    className?: string
    'data-attr'?: string
    'data-tooltip'?: string
}

type ObjectTagsProps =
    | (ObjectTagsPropsBase & {
          /** Tags CAN'T be added or removed. */
          staticOnly: true
          onChange?: never
          tagsAvailable?: never
      })
    | (ObjectTagsPropsBase & {
          /** Tags CAN be added or removed.*/
          staticOnly?: false
          onChange?: (tag: string, tags?: string[], id?: string) => void
          /** List of all tags that already exist. */
          tagsAvailable?: string[] /** Whether this field should be gated behind a "paywall". */
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
    className,
    'data-attr': dataAttr,
    'data-tooltip': dataTooltip,
}: ObjectTagsProps): JSX.Element {
    const objectTagId = useMemo(() => uniqueMemoizedIndex++, [])
    const logic = objectTagsLogic({ id: objectTagId, onChange, tags })
    const { guardAvailableFeature } = useActions(sceneLogic)
    const { addingNewTag, newTag, cleanedNewTag, deletedTags } = useValues(logic)
    const { setAddingNewTag, setNewTag, handleDelete, handleAdd } = useActions(logic)

    /** Displaying nothing is confusing, so in case of empty static tags we use a dash as a placeholder */
    const showPlaceholder = staticOnly && !tags?.length
    if (showPlaceholder && !style.color) {
        style.color = 'var(--muted)'
    }

    const onGuardClick = (callback: () => void): void => {
        guardAvailableFeature(
            AvailableFeature.TAGGING,
            'tags',
            'Tagging is an easy way to categorize events, properties, actions, insights, and more into custom groups.',
            () => {
                callback()
            }
        )
    }

    return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, ...style }} className={className} data-attr={dataAttr}>
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
                                              onClick={() =>
                                                  onGuardClick(() => {
                                                      handleDelete(tag)
                                                  })
                                              }
                                          />
                                      ))}
                              </Tag>
                          )
                      })}
            {!staticOnly && onChange && saving !== undefined && (
                <span style={{ display: 'inline-flex', fontWeight: 400 }}>
                    <Tag
                        onClick={() =>
                            onGuardClick(() => {
                                setAddingNewTag(true)
                            })
                        }
                        data-attr="button-add-tag"
                        data-tooltip={dataTooltip}
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
