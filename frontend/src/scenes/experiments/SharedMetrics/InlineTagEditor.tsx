import { useState } from 'react'

import { IconPencil, IconPlus } from '@posthog/icons'
import { LemonDropdown, LemonInputSelect, LemonTag } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { SharedMetric } from './sharedMetricLogic'

export function InlineTagEditor({
    metric,
    allTags,
    onSave,
    saving,
}: {
    metric: SharedMetric
    allTags: string[]
    onSave: (tags: string[]) => void
    saving: boolean
}): JSX.Element {
    const [isEditing, setIsEditing] = useState(false)
    const tags = metric.tags || []
    const hasTags = tags.length > 0

    return (
        <div className="inline-flex flex-wrap gap-0.5 items-center">
            {saving ? (
                <Spinner className="text-sm" />
            ) : (
                <>
                    {hasTags && <ObjectTags tags={tags} staticOnly />}
                    <LemonDropdown
                        visible={isEditing}
                        onClickOutside={() => setIsEditing(false)}
                        overlay={
                            <div className="p-2 w-[200px]">
                                <LemonInputSelect
                                    mode="multiple"
                                    allowCustomValues
                                    value={tags}
                                    options={allTags
                                        .filter((t) => !tags.includes(t))
                                        .map((t) => ({ key: t, label: t }))}
                                    onChange={(newTags) => {
                                        onSave(newTags)
                                        setIsEditing(false)
                                    }}
                                    placeholder='try "official"'
                                    autoFocus
                                    size="small"
                                />
                            </div>
                        }
                    >
                        <LemonTag
                            type="none"
                            onClick={() => setIsEditing(!isEditing)}
                            icon={hasTags ? <IconPencil /> : <IconPlus />}
                            className="border border-dashed cursor-pointer"
                            size="small"
                        >
                            {hasTags ? undefined : 'Add tag'}
                        </LemonTag>
                    </LemonDropdown>
                </>
            )}
        </div>
    )
}
