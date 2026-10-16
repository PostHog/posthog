// @ts-nocheck
// Test fixture for the generated prefer-codegen-api-namespaced-<product> rules.
// `semgrep --test` ignores paths.include, so every rule runs against this file and
// each line names the product rule that has to fire on it.

import api from 'lib/api'

// ruleid: prefer-codegen-api-namespaced-signals
const a = await api.signalReports.list()

// ruleid: prefer-codegen-api-namespaced-workflows
const b = await api.hogFlows.get(id)

// ruleid: prefer-codegen-api-namespaced-error_tracking
const c = await api.errorTracking.updateIssue(id, { status: 'resolved' })

// ruleid: prefer-codegen-api-namespaced-alerts
const d = await api.alerts.create({ name })

// A nested member chain is a different AST shape than api.<ns>.<method>().
// ruleid: prefer-codegen-api-namespaced-signals
const e = await api.signalSourceConfigs.runs.list({ limit: 10 })

// ruleid: prefer-codegen-api-namespaced-error_tracking
const f = await api.errorTracking.symbolSets.bulkDelete(ids)

// A core namespace is no product's to enforce.
// ok: prefer-codegen-api-namespaced-signals
const g = await api.tags.list(projectId)

// A namespace whose routes the generated clients gained is enforced from then on.
// ruleid: prefer-codegen-api-namespaced-posthog_ai
const h = await api.coreMemory.get()

// ruleid: prefer-codegen-api-namespaced-shared-activity
const l = await api.activity.list(id)

// The bare verbs are the other rule's job.
// ok: prefer-codegen-api-namespaced-signals
const i = await api.get(`api/projects/${projectId}/signals/reports/`)

// ok: prefer-codegen-api-namespaced-signals
const j = await signalsReportsList(projectId)

// nosemgrep: prefer-codegen-api-namespaced-signals
const k = await api.signalReports.availableReviewers()
