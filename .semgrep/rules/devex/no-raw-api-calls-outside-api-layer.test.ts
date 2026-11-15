// @ts-nocheck
// Test fixture for the no-raw-api-calls-outside-api-layer rules.
import { teamsList } from 'products/example/frontend/generated/api'

// ruleid: no-api-request-outside-api-layer
const a = await new ApiRequest().errorTrackingIssuesExists().get()

// ruleid: no-api-request-outside-api-layer
const b = await new ApiRequest().hogFlow(id).withAction('assets').withQueryString(params).get()

// ok: no-api-request-outside-api-layer
const c = await teamsList(projectId)

// ruleid: no-raw-fetch-to-api-outside-api-layer
const d = await fetch(`/api/projects/${teamId}/vision/observations/${id}/progress/`, { method: 'GET' })

// ruleid: no-raw-fetch-to-api-outside-api-layer
const e = await fetch('/api/vercel/connect/complete', { method: 'POST' })

// ruleid: no-raw-fetch-to-api-outside-api-layer
const f = await window.fetch(`${apiHost}/api/organizations/@current/`)

// ok: no-raw-fetch-to-api-outside-api-layer
const g = await fetch(assetUrl)

// A URL outside `/api/` is not checked.
// ok: no-raw-fetch-to-api-outside-api-layer
const h = await fetch('/static/example.json')

// ok: no-raw-fetch-to-api-outside-api-layer
const i = await fetch(`https://example.com/api/items`)

// A literal URL held in a local constant is still a raw call.
const apiUrl = '/api/projects/1/things/'
// ruleid: no-raw-fetch-to-api-outside-api-layer
const j = await fetch(apiUrl)

const staticUrl = '/static/example.json'
// ok: no-raw-fetch-to-api-outside-api-layer
const k = await fetch(staticUrl)

// ruleid: no-axios-in-frontend
import axios from 'axios'

// ruleid: no-axios-in-frontend
import { AxiosError } from 'axios'

// ruleid: no-axios-in-frontend
import * as axiosLib from 'axios'

// ok: no-axios-in-frontend
import { somethingElse } from 'other-http-client'
