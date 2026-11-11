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
