// @ts-nocheck
// Test fixture for the no-at-current-in-api-urls rule.

// ruleid: no-at-current-in-api-urls
const a = await api.get(`api/projects/@current/actions/${actionId}/references`)

// ruleid: no-at-current-in-api-urls
const b = await fetch('/api/organizations/@current/')

// A generated client takes the ID as an argument, so the URL never shows up here.
// ruleid: no-at-current-in-api-urls
const c = await billingUsageTimeseriesRetrieve('@current', params)

// ruleid: no-at-current-in-api-urls
await membersDestroy(currentOrganization?.id ?? '@current', userUuid)

// ruleid: no-at-current-in-api-urls
const iconUrl = `/api/projects/@current/mcp_servers/icon/?domain=${domain}`

// A query string or fragment also ends the path segment.
// ruleid: no-at-current-in-api-urls
const g = await fetch('/api/organizations/@current?expand=members')

// ok: no-at-current-in-api-urls
const d = await api.get(`api/projects/${currentProjectId}/actions/${actionId}/references`)

// The key lookup names the credential itself, not the user's last-opened project.
// ok: no-at-current-in-api-urls
const e = await fetch('/api/personal_api_keys/@current/')

// ok: no-at-current-in-api-urls
const f = 'shown to @currentUser'
