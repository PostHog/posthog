import { ReactNode, useEffect, useRef } from 'react'

import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle, Text, cn } from '@posthog/quill'

export interface CanvasTimelineRowProps {
    title: string
    meta: string
    icon: ReactNode
    label?: string
    /** Status badges, such as Live or a build that failed. */
    badges?: ReactNode
    /** Whether this row's version is the one on screen. */
    viewing: boolean
    live?: boolean
    draft?: boolean
    onOpen: () => void
    action?: ReactNode
    dataAttr: string
}

/** One entry on the timeline. Selecting the row shows that version in the canvas. */
export function CanvasTimelineRow({
    title,
    meta,
    icon,
    label,
    badges,
    viewing,
    live = false,
    draft = false,
    onOpen,
    action,
    dataAttr,
}: CanvasTimelineRowProps): JSX.Element {
    const rowRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (viewing) {
            rowRef.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [viewing])

    return (
        <div ref={rowRef} role="listitem" className="group/timeline-row flex gap-1">
            <div aria-hidden className="flex w-7 shrink-0 flex-col items-center">
                <span className="h-2 w-px bg-border group-first/timeline-row:invisible" />
                <span
                    className={cn(
                        'flex size-7 shrink-0 items-center justify-center rounded-full border bg-background text-muted-foreground [&_svg]:size-3.5',
                        draft && 'border-dashed',
                        live && 'border-success-foreground bg-success text-success-foreground',
                        viewing && !live && 'border-foreground text-foreground'
                    )}
                >
                    {icon}
                </span>
                <span className="w-px flex-1 bg-border group-last/timeline-row:invisible" />
            </div>
            <Item
                size="xs"
                data-selected={viewing || undefined}
                // The open button stretches over the whole row, so the row is one target and the action stays separate.
                // The app compiles fill tokens as plain classes only, so the selected fill is toggled, not a variant.
                className={cn(
                    'relative mb-1 min-w-0 flex-1 items-start',
                    viewing ? 'bg-fill-selected' : 'hover:bg-fill-hover'
                )}
            >
                <ItemContent className="min-w-0 gap-1">
                    {(label || badges) && (
                        <div className="flex flex-wrap items-center gap-1.5">
                            {label && (
                                <Text size="xs" weight="medium" translate="no">
                                    {label}
                                </Text>
                            )}
                            {badges}
                        </div>
                    )}
                    <ItemTitle className="min-w-0">
                        <button
                            type="button"
                            className="line-clamp-2 cursor-pointer text-left font-normal outline-none after:absolute after:inset-0 after:rounded-sm focus-visible:after:ring-2 focus-visible:after:ring-ring"
                            onClick={onOpen}
                            aria-current={viewing || undefined}
                            data-attr={dataAttr}
                        >
                            {title}
                        </button>
                    </ItemTitle>
                    <ItemDescription className="truncate">{meta}</ItemDescription>
                </ItemContent>
                {action && (
                    <ItemActions
                        className={cn(
                            'relative z-10 transition-opacity motion-reduce:transition-none',
                            !viewing &&
                                'opacity-0 group-hover/timeline-row:opacity-100 group-focus-within/timeline-row:opacity-100'
                        )}
                    >
                        {action}
                    </ItemActions>
                )}
            </Item>
        </div>
    )
}
