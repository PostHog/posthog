/**
 * The link dialog only takes keyboard input in its fields. A click on the dimmed overlay or on
 * the dialog outside its fields moves focus out of the URL field, and a second overlay click
 * closes the dialog and puts the cursor in the email body, so a paste lands in the email.
 * This customJS keeps focus in the dialog for those clicks and keeps an overlay click from
 * closing it. It acts only on dialogs with a text field. Cancel, Save and Escape still close the dialog. Unlayer opens the dialog in its
 * own modal or in a TinyMCE dialog, depending on the editor state. DOM-coupled by necessity:
 * if unlayer renames those classes, clicks behave as before.
 */
export const linkDialogFocusCustomJs = `
(function () {
    var DIALOG = '.ReactModal__Overlay, .tox-dialog-wrap'
    var CONTENT = '.ReactModal__Content > *, .tox-dialog'
    var CONTROLS = 'input, textarea, select, button, a, [role="button"], [role="combobox"], [role="listbox"], [role="option"], [contenteditable="true"]'

    var FIELDS = 'input:not([type="hidden"]), textarea'
    var lastField = null

    function guard(event) {
        var target = event.target
        var dialog = target && target.closest && target.closest(DIALOG)
        if (!dialog || target.closest(CONTROLS)) {
            return
        }
        // Only dialogs with a text field, so the preview and other modals still close on an overlay click.
        var field = lastField && dialog.contains(lastField) ? lastField : dialog.querySelector(FIELDS)
        if (!field) {
            return
        }
        event.preventDefault()
        if (!target.closest(CONTENT)) {
            event.stopImmediatePropagation()
        }
        // The editor moves focus after this handler runs, so restore it once that has happened.
        setTimeout(function () {
            if (field && !(document.activeElement && document.activeElement.closest && document.activeElement.closest(CONTROLS))) {
                field.focus()
            }
        }, 0)
    }

    document.addEventListener(
        'focusin',
        function (event) {
            if (event.target.closest && event.target.closest(DIALOG) && event.target.matches(FIELDS)) {
                lastField = event.target
            }
        },
        true
    )
    window.addEventListener('mousedown', guard, true)
    window.addEventListener('click', guard, true)
})()
`
