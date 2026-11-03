const EDITABLE_TARGET = 'input, textarea, [contenteditable]:not([contenteditable="false"])'
// A modal or popover owns Escape while it is open.
const ESCAPE_OWNERS = '.ReactModal__Overlay, .Popover'

export function shouldCloseOnEscape(event: KeyboardEvent): boolean {
    if (event.key !== 'Escape' || event.defaultPrevented) {
        return false
    }
    const isEditing = event.target instanceof Element && event.target.closest(EDITABLE_TARGET) !== null
    return !isEditing && document.querySelector(ESCAPE_OWNERS) === null
}
