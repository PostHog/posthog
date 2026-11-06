// The only script the admin console loads. A POST form disables its submit buttons when it submits, so a
// double click sends one request. The page reloads after every submit, which re-enables them. A button or
// link with `data-pending-label` shows that text until the next page loads, for pages that take a while.
const showPending = (element) => {
    element.setAttribute('aria-busy', 'true')
    element.dataset.originalLabel = element.textContent
    element.textContent = element.dataset.pendingLabel
}

document.addEventListener('submit', (event) => {
    const form = event.target
    if (!(form instanceof HTMLFormElement)) {
        return
    }
    for (const button of form.querySelectorAll('button[type="submit"]')) {
        if (button.dataset.pendingLabel) {
            showPending(button)
        }
        if (form.method.toLowerCase() === 'post' || button.dataset.pendingLabel) {
            button.disabled = true
            button.setAttribute('aria-busy', 'true')
        }
    }
})

document.addEventListener('click', (event) => {
    const link = event.target instanceof Element ? event.target.closest('a[data-pending-label]') : null
    if (link && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
        showPending(link)
    }
})

// The back button can restore a page in its pending state.
window.addEventListener('pageshow', () => {
    for (const element of document.querySelectorAll('[aria-busy="true"]')) {
        element.removeAttribute('aria-busy')
        if (element.dataset.originalLabel) {
            element.textContent = element.dataset.originalLabel
        }
        if (element instanceof HTMLButtonElement) {
            element.disabled = false
        }
    }
})

document.addEventListener('keydown', (event) => {
    const target = event.target
    const typing =
        target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select'))
    if (event.key !== '/' || typing || event.metaKey || event.ctrlKey || event.altKey) {
        return
    }
    const search = document.getElementById('team-search')
    if (search) {
        event.preventDefault()
        search.focus()
    }
})

document.querySelector('form[data-autofocus]')?.querySelector('input:not([type=hidden]), textarea, select')?.focus()
