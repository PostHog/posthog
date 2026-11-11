import './AnnotationsOverlay.scss'

import { IconPencil, IconTrash } from '@posthog/icons'
import { Badge, Button, Item, ItemActions, ItemContent, ItemHeader, ItemTitle, Text } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { LazyTextContent } from 'lib/components/RichContentEditor/LazyRichContent'

export interface QuillAnnotationCardProps {
    heading: string
    emoji?: string | null
    content: string
    isSystemAnnotation: boolean
    author: { name: string; email?: string; label: string }
    createdAt: string
    onEdit?: () => void
    onDelete?: () => void
}

export function QuillAnnotationCard({
    heading,
    emoji,
    content,
    isSystemAnnotation,
    author,
    createdAt,
    onEdit,
    onDelete,
}: QuillAnnotationCardProps): JSX.Element {
    return (
        <Item variant={isSystemAnnotation ? 'muted' : 'outline'} size="sm" role="listitem" className="AnnotationCard">
            <ItemHeader className="min-w-0">
                <ItemTitle className="w-auto min-w-0 flex-1 text-xs font-normal text-muted-foreground">
                    {emoji && <span className="shrink-0 text-base leading-none">{emoji}</span>}
                    <span className="truncate">{heading}</span>
                </ItemTitle>
                {(onEdit || onDelete) && (
                    <ItemActions className="shrink-0 gap-0">
                        {onEdit && (
                            <Button
                                size="icon-sm"
                                aria-label="Edit this annotation"
                                tooltip="Edit this annotation"
                                onClick={onEdit}
                            >
                                <IconPencil />
                            </Button>
                        )}
                        {onDelete && (
                            <Button
                                size="icon-sm"
                                aria-label="Delete this annotation"
                                tooltip="Delete this annotation"
                                onClick={onDelete}
                            >
                                <IconTrash />
                            </Button>
                        )}
                    </ItemActions>
                )}
            </ItemHeader>
            <ItemContent className="min-w-0 basis-full">
                <div className="flex items-start gap-2">
                    {isSystemAnnotation && <Badge variant="info">PostHog</Badge>}
                    <LazyTextContent
                        text={content}
                        className="min-w-0 flex-1"
                        data-attr="annotation-overlay-rendered-content"
                    />
                </div>
                {!isSystemAnnotation && (
                    <div className="flex items-center gap-2">
                        <QuillPersonAvatar name={author.name} email={author.email} size="xs" />
                        <Text size="xs" variant="muted" className="ph-no-capture m-0 truncate">
                            {author.label} • {createdAt}
                        </Text>
                    </div>
                )}
            </ItemContent>
        </Item>
    )
}
