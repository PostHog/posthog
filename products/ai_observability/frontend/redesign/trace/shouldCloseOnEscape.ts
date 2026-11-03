const EDITABLE_TARGET = 'input, textarea, [contenteditable]:not([contenteditable="false"])'
// A modal or popover owns the keyboard while it is open. react-modal appends a custom overlay class
// after its own, so `.ReactModal__Overlay` also matches LemonModal, LemonDialog and LemonDrawer.
const KEYBOARD_OWNERS = '.ReactModal__Overlay, .Popover'

export function isOverlayOpen(): boolean {
    return document.querySelector(KEYBOARD_OWNERS) !== null
}

export function shouldCloseOnEscape(event: KeyboardEvent): boolean {
    if (event.key !== 'Escape' || event.defaultPrevented) {
        return false
    }
    const isEditing = event.target instanceof Element && event.target.closest(EDITABLE_TARGET) !== null
    return !isEditing && !isOverlayOpen()
}
