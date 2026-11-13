import { useState } from 'react'

import { IconPencil, IconPlus } from '@posthog/icons'
import { LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TagsInputSelect } from 'lib/components/TagsInputSelect'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { SharedMetric } from './sharedMetricLogic'

export function InlineTagEditor({
    metric,
    onSave,
    saving,
}: {
    metric: SharedMetric
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
                                <TagsInputSelect
                                    value={tags}
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
