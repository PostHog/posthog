import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CSSProperties, useMemo } from 'react'

import { IconPencil, IconPlus } from '@posthog/icons'
import { LemonInputSelect, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { objectTagsLogic } from 'lib/components/ObjectTags/objectTagsLogic'
import { colorForString } from 'lib/utils'

import { AvailableFeature } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'

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
          onBlur?: never
          tagsAvailable?: never
      })
    | (ObjectTagsPropsBase & {
          /** Tags CAN be added or removed.*/
          staticOnly?: false
          onChange?: (tags: string[]) => void
          onBlur?: () => void
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
    onBlur,
    saving, // Required unless `staticOnly`
    tagsAvailable,
    style = {},
    staticOnly = false,
    className,
    'data-attr': dataAttr,
}: ObjectTagsProps): JSX.Element {
    const objectTagId = useMemo(() => uniqueMemoizedIndex++, [])
    const logic = objectTagsLogic({ id: objectTagId, onChange })
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { editingTags } = useValues(logic)
    const { setEditingTags, setTags } = useActions(logic)

    /** Displaying nothing is confusing, so in case of empty static tags we use a dash as a placeholder */
    const showPlaceholder = staticOnly && !tags?.length
    if (showPlaceholder && !style.color) {
        style.color = 'var(--color-text-secondary)'
    }

    const onGuardClick = (callback: () => void): void => {
        guardAvailableFeature(AvailableFeature.TAGGING, () => {
            callback()
        })
    }

    const hasTags = tagsAvailable && tagsAvailable.length > 0

    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            className={clsx(className, 'inline-flex flex-wrap gap-0.5 items-center')}
            data-attr={dataAttr}
        >
            {editingTags ? (
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={tags}
                    options={tagsAvailable?.map((t) => ({ key: t, label: t }))}
                    onChange={setTags}
                    onBlur={() => {
                        setEditingTags(false)
                        onBlur?.()
                    }}
                    loading={saving}
                    data-attr="new-tag-input"
                    placeholder='try "official"'
                    autoFocus
                />
            ) : (
                <>
                    {showPlaceholder
                        ? '—'
                        : tags
                              .filter((t) => !!t)
                              .map((tag, index) => {
                                  return (
                                      <LemonTag key={index} type={COLOR_OVERRIDES[tag] || colorForString(tag)}>
                                          {tag}
                                      </LemonTag>
                                  )
                              })}
                    {!staticOnly && onChange && saving !== undefined && (
                        <span className="inline-flex font-normal">
                            <LemonTag
                                type="none"
                                onClick={() =>
                                    onGuardClick(() => {
                                        setEditingTags(true)
                                    })
                                }
                                data-attr="button-add-tag"
                                icon={hasTags ? <IconPencil /> : <IconPlus />}
                                className="border border-dashed"
                                size="small"
                            >
                                {hasTags ? 'Edit tags' : 'Add tag'}
                            </LemonTag>
                        </span>
                    )}
                </>
            )}
        </div>
    )
}
