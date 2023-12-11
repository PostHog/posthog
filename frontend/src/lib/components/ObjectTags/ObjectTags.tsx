// eslint-disable-next-line no-restricted-imports
import { CloseOutlined, SyncOutlined } from '@ant-design/icons'
import { IconPlus } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { Select } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { objectTagsLogic } from 'lib/components/ObjectTags/objectTagsLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { colorForString } from 'lib/utils'
import { CSSProperties, useMemo } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'

import { AvailableFeature } from '~/types'

import { SelectGradientOverflow } from '../SelectGradientOverflow'

interface ObjectTagsPropsBase {
    tags: string[]
    saving?: boolean
    style?: CSSProperties
    id?: string
    className?: string
    'data-attr'?: string
}

export type ObjectTagsProps =
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

const COLOR_OVERRIDES: Record<string, LemonTagType> = {
    official: 'success',
    approved: 'success',
    verified: 'success',
    deprecated: 'danger',
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
}: ObjectTagsProps): JSX.Element {
    const objectTagId = useMemo(() => uniqueMemoizedIndex++, [])
    const logic = objectTagsLogic({ id: objectTagId, onChange, tags })
    const { guardAvailableFeature } = useActions(sceneLogic)
    const { addingNewTag, cleanedNewTag, deletedTags } = useValues(logic)
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
        // eslint-disable-next-line react/forbid-dom-props
        <div style={style} className={clsx(className, 'flex flex-wrap gap-2 items-center')} data-attr={dataAttr}>
            {showPlaceholder
                ? '—'
                : tags
                      .filter((t) => !!t)
                      .map((tag, index) => {
                          return (
                              <LemonTag
                                  key={index}
                                  type={COLOR_OVERRIDES[tag] || colorForString(tag)}
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
                              </LemonTag>
                          )
                      })}
            {saving && <Spinner />}
            {!staticOnly && onChange && saving !== undefined && (
                <span className="inline-flex font-normal">
                    <LemonTag
                        type="none"
                        onClick={() =>
                            onGuardClick(() => {
                                setAddingNewTag(true)
                            })
                        }
                        data-attr="button-add-tag"
                        icon={<IconPlus />}
                        className="border border-dashed"
                        style={{
                            display: addingNewTag ? 'none' : 'inline-flex',
                        }}
                    >
                        Add tag
                    </LemonTag>
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
                            onChange={(changedValue) => handleAdd(changedValue)}
                            loading={saving}
                            onSearch={setNewTag}
                            placeholder='try "official"'
                        >
                            {cleanedNewTag ? (
                                <Select.Option
                                    key={`${cleanedNewTag}_${id}`}
                                    value={cleanedNewTag}
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
