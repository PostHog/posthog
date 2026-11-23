import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { TagDefinitionApi } from '../generated/api.schemas'

export function TaggerTagList({ tags }: { tags: TagDefinitionApi[] }): JSX.Element {
    if (tags.length === 0) {
        return <span className="text-muted">Any tag the Hog code returns</span>
    }
    return (
        <div className="flex flex-wrap gap-1">
            {tags.map((tag) => (
                <Tooltip key={tag.name} title={tag.description || undefined}>
                    <LemonTag type="highlight">{tag.name}</LemonTag>
                </Tooltip>
            ))}
        </div>
    )
}
