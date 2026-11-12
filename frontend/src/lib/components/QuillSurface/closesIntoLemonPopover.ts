import { isInsideOpenPopover } from 'lib/lemon-ui/Popover/Popover'

interface QuillOpenChangeDetails {
    reason: string
    event: Event
}

// A quill popup that hosts Lemon content must not close when the click or focus lands in a Lemon popup,
// because Lemon popups portal outside the quill one.
export function closesIntoLemonPopover(open: boolean, details: QuillOpenChangeDetails): boolean {
    if (open) {
        return false
    }
    const landedOn =
        details.reason === 'focus-out'
            ? (details.event as FocusEvent).relatedTarget
            : details.reason === 'outside-press'
              ? details.event.target
              : null
    return isInsideOpenPopover(landedOn)
}
