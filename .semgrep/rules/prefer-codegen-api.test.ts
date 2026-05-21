// @ts-nocheck
// Test fixture for prefer-codegen-api rule.

import api from 'lib/api'

// ruleid: prefer-codegen-api
const a = await api.get(`api/foo`)

// ruleid: prefer-codegen-api
const b = await api.post(`api/foo`, {})

// ruleid: prefer-codegen-api
const c = await api.create(`api/foo`, {})

// ruleid: prefer-codegen-api
const d = await api.update(`api/foo/${id}`, {})

// ruleid: prefer-codegen-api
const e = await api.delete(`api/foo/${id}`)

// ruleid: prefer-codegen-api
const f = await api.patch(`api/foo/${id}`, {})

// ruleid: prefer-codegen-api
const g = await api.put(`api/foo/${id}`, {})

// ruleid: prefer-codegen-api
const h = await api.create<Foo>(`api/foo`, {})

// ruleid: prefer-codegen-api
const i = await api.get<Foo>(`api/foo`)

// ruleid: prefer-codegen-api
const i2 = await api.get<PaginatedResponse<Foo>>(`api/foo`)

// ruleid: prefer-codegen-api
const i3 = await api.get<CountedPaginatedResponse<ChangeRequest>>(`api/foo`)

// ok: prefer-codegen-api
const j = await api.integrations.authorizeUrl()

// ok: prefer-codegen-api
const k = await api.dashboards.list()

// ok: prefer-codegen-api
const l = await legalDocumentsList(orgId)

// nosemgrep: prefer-codegen-api
const m = await api.get(`api/foo`)
