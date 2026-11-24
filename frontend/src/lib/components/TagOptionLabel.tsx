import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'

import { TAG_OBJECT_NOUNS, TagOption } from './tagSelectLogic'

export function TagOptionLabel({ tag, count, total_count, objectType }: TagOption): JSX.Element {
    if (count === undefined) {
        return (
            <span className="min-w-0 flex-1 truncate" title={tag}>
                {tag}
            </span>
        )
    }
    const countLabel = <span className="text-muted tabular-nums shrink-0">{count}</span>
    return (
        <span className="flex w-full min-w-0 flex-1 items-center justify-between gap-2">
            <span className="min-w-0 truncate" title={tag}>
                {tag}
            </span>
            {total_count === undefined || objectType === undefined ? (
                countLabel
            ) : (
                <Tooltip title={getTagUsageDescription(count, total_count, TAG_OBJECT_NOUNS[objectType])}>
                    <span className="text-muted tabular-nums shrink-0">
                        {count} ({total_count})
                    </span>
                </Tooltip>
            )}
        </span>
    )
}

function getTagUsageDescription(
    count: number,
    totalCount: number,
    [singular, plural]: readonly [string, string]
): string {
    const objects = `${pluralize(count, singular, plural)} ${count === 1 ? 'uses' : 'use'} this tag.`
    const total = `${pluralize(totalCount, 'item')} ${totalCount === 1 ? 'uses' : 'use'} this tag across the project.`
    return `${objects} ${total}`
}
