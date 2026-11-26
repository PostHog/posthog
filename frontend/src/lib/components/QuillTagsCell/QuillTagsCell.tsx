import { Badge, Text } from '@posthog/quill'

const VISIBLE_TAGS = 2

/** The tags of a quill list row: the first two as badges, then a count of the rest that names them on hover. */
export function QuillTagsCell({ tags }: { tags: string[] }): JSX.Element {
    if (!tags.length) {
        return (
            <Text size="xs" variant="muted">
                –
            </Text>
        )
    }

    return (
        <div className="flex items-center gap-1">
            {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                <Badge key={tag} className="max-w-24 truncate">
                    {tag}
                </Badge>
            ))}
            {tags.length > VISIBLE_TAGS && (
                <Text size="xs" variant="muted" title={tags.slice(VISIBLE_TAGS).join(', ')}>
                    {`+${tags.length - VISIBLE_TAGS}`}
                </Text>
            )}
        </div>
    )
}
