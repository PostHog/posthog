import { Badge, Button } from '@posthog/quill'

const VISIBLE_TAGS = 4

export interface QuillKeyTag {
    id: string
    name: string
    restricted?: boolean
}

export function QuillKeyTagList({ tags, onMoreClick }: { tags: QuillKeyTag[]; onMoreClick: () => void }): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-1">
            {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                <Badge key={tag.id} className={tag.restricted ? 'line-through opacity-60' : undefined}>
                    {tag.name}
                </Badge>
            ))}
            {tags.length > VISIBLE_TAGS && (
                <Button
                    size="xs"
                    variant="outline"
                    tooltip={tags
                        .slice(VISIBLE_TAGS)
                        .map((tag) => tag.name)
                        .join(', ')}
                    onClick={onMoreClick}
                >
                    {`+${tags.length - VISIBLE_TAGS} more`}
                </Button>
            )}
        </span>
    )
}
