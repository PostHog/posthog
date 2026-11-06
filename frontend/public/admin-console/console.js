// The only script file the admin console loads. A POST form disables its submit buttons when it submits, so a
// double click sends one request. The page reloads after every submit, which re-enables them.
document.addEventListener('submit', (event) => {
    const form = event.target
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post') {
        return
    }
    for (const button of form.querySelectorAll('button[type="submit"]')) {
        button.disabled = true
        button.setAttribute('aria-busy', 'true')
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
