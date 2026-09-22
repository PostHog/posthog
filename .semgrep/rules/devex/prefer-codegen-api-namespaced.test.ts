// @ts-nocheck
// Test fixture for the prefer-codegen-api-namespaced rule.

import api from 'lib/api'

// ruleid: prefer-codegen-api-namespaced
const a = await api.signalReports.list()

// ruleid: prefer-codegen-api-namespaced
const b = await api.hogFlows.get(id)

// ruleid: prefer-codegen-api-namespaced
const c = await api.errorTracking.updateIssue(id, { status: 'resolved' })

// ruleid: prefer-codegen-api-namespaced
const d = await api.alerts.create({ name })

// ok: prefer-codegen-api-namespaced
const e = await api.signalTeamConfig.get()

// ok: prefer-codegen-api-namespaced
const f = await api.coreMemory.get()

// The bare verbs are the other rule's job.
// ok: prefer-codegen-api-namespaced
const g = await api.get(`api/projects/${projectId}/signals/reports/`)

// ok: prefer-codegen-api-namespaced
const h = await signalsReportsList(projectId)

// nosemgrep: prefer-codegen-api-namespaced
const i = await api.signalReports.availableReviewers()
