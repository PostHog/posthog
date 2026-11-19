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
    // A disabled button posts no value, so the value of the button that submits moves to a hidden field first.
    const submitter = event.submitter
    if (submitter instanceof HTMLButtonElement && submitter.name) {
        const field = document.createElement('input')
        field.type = 'hidden'
        field.name = submitter.name
        field.value = submitter.value
        form.append(field)
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

// A Decision block: a key such as ArrowRight presses the button or link that names it, unless staff are typing.
document.addEventListener('keydown', (event) => {
    const target = event.target
    const typing =
        target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select'))
    if (typing || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) {
        return
    }
    const control = [...document.querySelectorAll('[data-console-key]')].find(
        (element) => element.dataset.consoleKey === event.key
    )
    if (control instanceof HTMLElement && !control.hasAttribute('disabled')) {
        event.preventDefault()
        control.click()
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

const toolFilter = document.querySelector('[data-tool-filter]')
if (toolFilter instanceof HTMLInputElement) {
    const groups = [...document.querySelectorAll('[data-tool-group]')]
    const renderedOpen = new Map(groups.map((group) => [group, group.open]))
    const emptyNote = document.querySelector('[data-tool-filter-empty]')
    toolFilter.hidden = false
    const applyFilter = () => {
        const query = toolFilter.value.trim().toLowerCase()
        let matches = 0
        for (const group of groups) {
            let groupMatches = 0
            for (const item of group.querySelectorAll('[data-tool-title]')) {
                const match = !query || item.dataset.toolTitle.includes(query)
                item.hidden = !match
                groupMatches += match ? 1 : 0
            }
            group.parentElement.hidden = groupMatches === 0
            const count = group.querySelector('[data-tool-count]')
            if (count) {
                count.textContent = String(groupMatches)
            }
            group.open = query ? groupMatches > 0 : renderedOpen.get(group)
            matches += groupMatches
        }
        if (emptyNote) {
            emptyNote.hidden = matches > 0
        }
    }
    toolFilter.addEventListener('input', applyFilter)
    toolFilter.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && toolFilter.value) {
            toolFilter.value = ''
            applyFilter()
        } else if (event.key === 'Enter' && toolFilter.value.trim()) {
            const first = document.querySelector('[data-tool-group][open] [data-tool-title]:not([hidden]) a')
            if (first instanceof HTMLAnchorElement) {
                event.preventDefault()
                first.click()
            }
        }
    })
}

// The sidebar scrolls on its own, so the current tool can sit below its fold. Scroll the sidebar, not the page.
const navScroller = document.querySelector('[data-nav-scroller]')
const currentNavLink = navScroller?.querySelector('[aria-current="page"]')
if (navScroller instanceof HTMLElement && currentNavLink instanceof HTMLElement) {
    const linkBottom = currentNavLink.offsetTop + currentNavLink.offsetHeight
    if (linkBottom > navScroller.clientHeight) {
        navScroller.scrollTop = linkBottom - navScroller.clientHeight / 2
    }
}
