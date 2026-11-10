import type { MutableRefObject, ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { Button, Heading, ItemGroup, Popover, PopoverContent, Text } from '@posthog/quill'

import { isInsideOpenPopover } from 'lib/lemon-ui/Popover/Popover'

export interface QuillAnnotationsPopoverProps {
    open: boolean
    anchor: HTMLElement | null
    popupRef: MutableRefObject<HTMLDivElement | null>
    /** Clicks and focus inside these (the badges, the annotation modal) keep the popover open. */
    insideRefs: MutableRefObject<HTMLDivElement | null>[]
    title: string
    locked: boolean
    annotationCount: number
    onClose: () => void
    onMouseEnter: () => void
    onMouseLeave?: () => void
    onAddAnnotation?: () => void
    children: ReactNode
}

export function QuillAnnotationsPopover({
    open,
    anchor,
    popupRef,
    insideRefs,
    title,
    locked,
    annotationCount,
    onClose,
    onMouseEnter,
    onMouseLeave,
    onAddAnnotation,
    children,
}: QuillAnnotationsPopoverProps): JSX.Element {
    return (
        <Popover
            open={open}
            onOpenChange={(next, details) => {
                if (next) {
                    return
                }
                const landedOn =
                    details.reason === 'focus-out'
                        ? (details.event as FocusEvent).relatedTarget
                        : details.reason === 'outside-press'
                          ? details.event.target
                          : null
                if (
                    isInsideOpenPopover(landedOn) ||
                    (landedOn instanceof Node && insideRefs.some((ref) => ref.current?.contains(landedOn)))
                ) {
                    details.cancel()
                    return
                }
                onClose()
            }}
        >
            <PopoverContent
                ref={popupRef}
                anchor={anchor}
                side="top"
                arrow
                initialFocus={false}
                finalFocus={false}
                onMouseEnter={onMouseEnter}
                onMouseLeave={onMouseLeave}
                data-hog-charts-interactive-overlay
                className="AnnotationsPopover--quill w-[22rem] max-h-(--available-height) gap-0 p-0"
            >
                <div className="flex items-center gap-2 border-b px-3 py-2">
                    <Heading size="sm" render={<h3 className="m-0" />} className="min-w-0 flex-1 truncate">
                        {title}
                    </Heading>
                    {locked && (
                        <Button size="icon" aria-label="Close" tooltip="Close" onClick={onClose}>
                            <IconX />
                        </Button>
                    )}
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto scroll-mask-y-4 scroll-py-4 p-3">
                    {annotationCount > 0 ? (
                        <ItemGroup className="gap-2">{children}</ItemGroup>
                    ) : (
                        <Text size="xs" variant="muted" className="m-0">
                            There are no annotations in this period.
                        </Text>
                    )}
                </div>
                {onAddAnnotation && (
                    <div className="flex justify-end border-t px-3 py-2">
                        <Button
                            variant="primary"
                            onClick={onAddAnnotation}
                            disabledReason={
                                locked ? undefined : 'Click the marker on the chart to add an annotation here'
                            }
                        >
                            Add annotation
                        </Button>
                    </div>
                )}
            </PopoverContent>
        </Popover>
    )
}
