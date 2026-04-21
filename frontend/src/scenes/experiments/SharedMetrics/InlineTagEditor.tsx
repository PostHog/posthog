import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

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
    const tags = metric.tags || []

    return (
        <ObjectTags
            tags={tags}
            tagsAvailable={allTags.filter((tag) => !tags.includes(tag))}
            onChange={onSave}
            saving={saving}
        />
    )
}
