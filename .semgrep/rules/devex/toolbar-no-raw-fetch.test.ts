// @ts-nocheck
// Test fixture for the toolbar-no-raw-fetch rule.

// ruleid: toolbar-no-raw-fetch
const a = await fetch('/api/projects/@current/actions/')

// ruleid: toolbar-no-raw-fetch
const b = await fetch(url, { method: 'POST', body: JSON.stringify(payload) })

// ruleid: toolbar-no-raw-fetch
void fetch(`${host}/toolbar_oauth/check`, { method: 'HEAD' })

// ruleid: toolbar-no-raw-fetch
const c = await window.fetch(url)

// ruleid: toolbar-no-raw-fetch
const d = await globalThis.fetch(url)

// ok: toolbar-no-raw-fetch
const e = await safeFetch(url, { credentials: 'include' })

// ok: toolbar-no-raw-fetch
const f = await toolbarFetch('/api/projects/@current/actions/', 'GET')

// ok: toolbar-no-raw-fetch
const g = await toolbarApi.actions.list({ context: 'load_actions' })
