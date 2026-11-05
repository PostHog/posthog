// The only script the admin console loads. A POST form disables its submit buttons when it submits, so a
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
