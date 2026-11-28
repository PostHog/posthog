import { IconPencil, IconPlus } from '@posthog/icons'
import { Badge, Button, Popover, PopoverContent, PopoverTrigger, Text, cn } from '@posthog/quill'

import type { LoadTags } from 'lib/components/tagSelectLogic'

import { QuillObjectTagsEditor } from './QuillObjectTagsEditor'

const BADGE_VARIANT_OVERRIDES: Record<string, 'success' | 'destructive'> = {
    official: 'success',
    approved: 'success',
    verified: 'success',
    deprecated: 'destructive',
}

export interface QuillObjectTagsProps {
    tags: string[]
    visibleTags: string[]
    overflowTags: string[]
    showPlaceholder: boolean
    hasTags: boolean
    editing: boolean
    canEdit: boolean
    onStartEditing: () => void
    onStopEditing: () => void
    onChange: (tags: string[]) => void
    saving?: boolean
    tagsAvailable?: string[]
    loadTags?: LoadTags
    addLabel: string
    editLabel: string
    inputPlaceholder: string
    onTagClick?: (tag: string) => void
    showOverflowTags: boolean
    onShowOverflowTagsChange: (show: boolean) => void
    showOverflowLabel: boolean
    compact: boolean
    wrap: boolean
    editorFullWidth: boolean
    className?: string
    'data-attr'?: string
}

export function QuillObjectTags({
    tags,
    visibleTags,
    overflowTags,
    showPlaceholder,
    hasTags,
    editing,
    canEdit,
    onStartEditing,
    onStopEditing,
    onChange,
    saving,
    tagsAvailable,
    loadTags,
    addLabel,
    editLabel,
    inputPlaceholder,
    onTagClick,
    showOverflowTags,
    onShowOverflowTagsChange,
    showOverflowLabel,
    compact,
    wrap,
    editorFullWidth,
    className,
    'data-attr': dataAttr,
}: QuillObjectTagsProps): JSX.Element {
    const renderTag = (tag: string, index: number): JSX.Element => {
        const variant = BADGE_VARIANT_OVERRIDES[tag] ?? 'default'
        const label = (
            <span className={cn(compact || wrap ? 'min-w-0' : undefined, compact ? 'truncate' : undefined)} title={tag}>
                {tag}
            </span>
        )

        return onTagClick ? (
            <Badge key={index} variant={variant} render={<button type="button" onClick={() => onTagClick(tag)} />}>
                {label}
            </Badge>
        ) : (
            <Badge key={index} variant={variant}>
                {label}
            </Badge>
        )
    }

    return (
        <div
            className={cn(
                className,
                'inline-flex items-center gap-1',
                compact ? 'min-w-0 flex-nowrap' : 'flex-wrap',
                wrap && 'max-w-full min-w-0',
                editing && editorFullWidth && 'w-full min-w-0'
            )}
            data-attr={dataAttr}
        >
            {editing ? (
                <QuillObjectTagsEditor
                    tags={tags}
                    onChange={onChange}
                    onStopEditing={onStopEditing}
                    saving={saving}
                    tagsAvailable={tagsAvailable}
                    loadTags={loadTags}
                    placeholder={inputPlaceholder}
                    fullWidth={editorFullWidth}
                />
            ) : (
                <>
                    {showPlaceholder ? (
                        <Text size="xs" variant="muted" render={<span />}>
                            -
                        </Text>
                    ) : (
                        visibleTags.map(renderTag)
                    )}
                    {overflowTags.length > 0 && (
                        <Popover open={showOverflowTags} onOpenChange={onShowOverflowTagsChange}>
                            <PopoverTrigger
                                render={
                                    <Button
                                        size="xs"
                                        data-attr={dataAttr ? `${dataAttr}-overflow` : undefined}
                                        aria-label={`Show ${overflowTags.length} more ${overflowTags.length === 1 ? 'tag' : 'tags'}`}
                                    >
                                        <span>{`+${overflowTags.length}${showOverflowLabel ? ' more' : ''}`}</span>
                                    </Button>
                                }
                            />
                            <PopoverContent className="max-w-md">
                                <div className="flex flex-wrap gap-1">{overflowTags.map(renderTag)}</div>
                            </PopoverContent>
                        </Popover>
                    )}
                    {canEdit && (
                        <Button size="xs" variant="outline" onClick={onStartEditing} data-attr="button-add-tag">
                            {hasTags ? <IconPencil /> : <IconPlus />}
                            {hasTags ? editLabel : addLabel}
                        </Button>
                    )}
                </>
            )}
        </div>
    )
}
