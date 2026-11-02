import { LemonSelect } from '@posthog/lemon-ui'

import { TagSelect } from 'lib/components/TagSelect'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { ResourceTagFilters } from './resourceTagFilters'

export function ResourceTagFilter({
    filters,
    onChange,
    size = 'medium',
}: {
    filters: ResourceTagFilters
    onChange: (filters: ResourceTagFilters) => void
    size?: 'small' | 'medium'
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <TagSelect
                defaultLabel="Tags"
                size={size}
                value={filters.tags}
                onChange={(tags) => {
                    if (tags.length > 20) {
                        lemonToast.error('Choose up to 20 tags to filter by')
                        return
                    }
                    onChange({ tags, tag_match: filters.tag_match })
                }}
                listDataAttr="aio-resource-tags-filter"
            />
            {filters.tags.length > 1 && (
                <LemonSelect
                    size={size}
                    value={filters.tag_match}
                    onChange={(tag_match) => onChange({ tags: filters.tags, tag_match })}
                    options={[
                        { value: 'any', label: 'Match any' },
                        { value: 'all', label: 'Match all' },
                    ]}
                    data-attr="aio-resource-tags-match"
                />
            )}
        </div>
    )
}
