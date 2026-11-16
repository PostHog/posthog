import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { isInsideOpenPopover } from 'lib/lemon-ui/Popover/Popover'

export interface QuillHogQLMathPopoverProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    value: string
    onChange: (value: string) => void
    'data-attr': string
}

export function QuillHogQLMathPopover({
    open,
    onOpenChange,
    value,
    onChange,
    'data-attr': dataAttr,
}: QuillHogQLMathPopoverProps): JSX.Element {
    return (
        <Popover
            open={open}
            onOpenChange={(next, details) => {
                const landedOn =
                    details.reason === 'focus-out'
                        ? (details.event as FocusEvent).relatedTarget
                        : details.reason === 'outside-press'
                          ? details.event.target
                          : null
                if (!next && isInsideOpenPopover(landedOn)) {
                    details.cancel()
                    return
                }
                onOpenChange(next)
            }}
        >
            <PopoverTrigger render={<Button variant="outline" left className="w-full min-w-0" data-attr={dataAttr} />}>
                <code className="min-w-0 truncate">{value}</code>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div data-not-quill className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                    <HogQLEditor value={value} onChange={onChange} />
                </div>
            </PopoverContent>
        </Popover>
    )
}
