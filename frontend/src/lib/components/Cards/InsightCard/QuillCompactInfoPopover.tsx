import { useEffect } from 'react'

import { IconInfo } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { CompactInfoPopoverContent, type CompactInfoPopoverContentProps } from './CompactInfoPopoverContent'

export function QuillCompactInfoPopover({
    onVisibilityChange,
    ...contentProps
}: CompactInfoPopoverContentProps & { onVisibilityChange?: (visible: boolean) => void }): JSX.Element {
    useEffect(() => () => onVisibilityChange?.(false), [onVisibilityChange])

    return (
        <Popover onOpenChange={(open) => onVisibilityChange?.(open)}>
            <PopoverTrigger
                openOnHover
                delay={300}
                closeDelay={800}
                render={
                    <Button
                        size="icon-xs"
                        className="ml-1 shrink-0"
                        aria-label="Insight details"
                        data-attr="card-meta-info"
                    />
                }
            >
                <IconInfo />
            </PopoverTrigger>
            <PopoverContent arrow className="p-0">
                <CompactInfoPopoverContent {...contentProps} />
            </PopoverContent>
        </Popover>
    )
}
