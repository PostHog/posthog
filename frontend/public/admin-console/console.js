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

// A Secret block on a result page: a click in the field selects the value, and the button copies it.
document.addEventListener('click', (event) => {
    const target = event.target
    if (target instanceof HTMLInputElement && target.hasAttribute('data-console-secret')) {
        target.select()
        return
    }
    const button = target instanceof Element ? target.closest('button[data-console-copy]') : null
    const field = button ? document.getElementById(button.dataset.consoleCopy) : null
    if (!(field instanceof HTMLInputElement)) {
        return
    }
    const selectForKeyboardCopy = () => {
        field.select()
        button.textContent = 'Selected. Copy with the keyboard'
    }
    // Browsers leave navigator.clipboard undefined on a page served over plain HTTP outside localhost.
    if (!navigator.clipboard) {
        selectForKeyboardCopy()
        return
    }
    navigator.clipboard.writeText(field.value).then(() => {
        button.textContent = 'Copied'
    }, selectForKeyboardCopy)
})

document.querySelector('form[data-autofocus]')?.querySelector('input:not([type=hidden]), textarea, select')?.focus()

// Live blocks ask the server for a fresh copy of themselves while their data-refresh-seconds is set, for
// example the runs of a job that is still going. Each block waits for its answer before it asks again, waits
// longer after a failure, and pauses while the tab is hidden. A response without the console's header (a login
// page after the session ended, an error page) stops the refreshes instead of replacing the block.
const LIVE_MAX_BACKOFF = 4

function scheduleLiveRefresh(element, failures) {
    const seconds = Number(element.dataset.refreshSeconds)
    if (!seconds) {
        return
    }
    const delay = seconds * 1000 * 2 ** Math.min(failures, LIVE_MAX_BACKOFF)
    setTimeout(() => refreshLiveBlock(element, failures), delay)
}

async function refreshLiveBlock(element, failures) {
    if (!element.isConnected) {
        return
    }
    if (document.hidden) {
        document.addEventListener('visibilitychange', () => refreshLiveBlock(element, failures), { once: true })
        return
    }
    let response
    let body
    try {
        response = await fetch(element.dataset.consoleLive, { credentials: 'same-origin', redirect: 'manual' })
        body = await response.text()
    } catch {
        scheduleLiveRefresh(element, failures + 1)
        return
    }
    if (response.status >= 500) {
        scheduleLiveRefresh(element, failures + 1)
        return
    }
    if (!response.ok || response.headers.get('X-Console-Live') !== '1') {
        return
    }
    const template = document.createElement('template')
    template.innerHTML = body.trim()
    const replacement = template.content.firstElementChild
    if (!replacement || !replacement.hasAttribute('data-console-live')) {
        return
    }
    element.replaceWith(replacement)
    scheduleLiveRefresh(replacement, 0)
}

for (const element of document.querySelectorAll('[data-console-live]')) {
    scheduleLiveRefresh(element, 0)
}
