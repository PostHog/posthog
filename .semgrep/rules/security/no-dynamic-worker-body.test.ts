// @ts-nocheck
// Test fixture for the no-dynamic-worker-body rule.

// ruleid: no-dynamic-worker-body
const a = new Worker(URL.createObjectURL(new Blob([source], { type: 'application/javascript' })))

// ruleid: no-dynamic-worker-body
const b = new SharedWorker(URL.createObjectURL(new Blob([userSuppliedCode])))

// ruleid: no-dynamic-worker-body
const c = new Worker(window.URL.createObjectURL(new Blob([template, payload])), { name: 'thing' })

// ruleid: no-dynamic-worker-body
const d = new Worker('data:text/javascript;charset=utf-8,' + encodeURIComponent(source))

// ruleid: no-dynamic-worker-body
const e = new Worker(`data:text/javascript,${encodeURIComponent(body)}`)

// Revoking an object URL needs it held in a variable, so this is the shape a developer
// writes when the blob worker is written correctly.
const objectUrl = URL.createObjectURL(new Blob([source]))
// ruleid: no-dynamic-worker-body
const k = new Worker(objectUrl)

// ruleid: no-dynamic-worker-body
const l = new Worker(URL.createObjectURL(blob))

// ruleid: no-dynamic-worker-body
const m = new Worker(globalThis.URL.createObjectURL(new Blob([source])))

const dataUrl = 'data:text/javascript,' + encodeURIComponent(source)
// ruleid: no-dynamic-worker-body
const n = new Worker(dataUrl)

const templatedDataUrl = `data:text/javascript,${encodeURIComponent(body)}`
// ruleid: no-dynamic-worker-body
const o = new Worker(templatedDataUrl)

// A same-origin file. This is the shape every first-party worker in the app uses, and it
// needs no blob: allowance.
// ok: no-dynamic-worker-body
const f = new Worker(new URL('./hogqlParser.worker.ts', import.meta.url), { type: 'module' })

// ok: no-dynamic-worker-body
const g = new Worker('/static/decompressionWorker.js', { type: 'module' })

// ok: no-dynamic-worker-body
const h = new Worker(WORKER_URL, { type: 'module' })

// Nothing in scope puts a blob or a data URL in this variable, so there is no flow to
// report. A worker URL that arrives from outside the file is not something this rule can
// judge.
// ok: no-dynamic-worker-body
const i = new Worker(precomputedUrl)

// A same-origin path assembled from a value. The scheme decides, not the concatenation
// or the interpolation, so all three of these stay clean.
// ok: no-dynamic-worker-body
const p = new Worker('/static/workers/' + workerName, { type: 'module' })

// ok: no-dynamic-worker-body
const q = new Worker(`/static/workers/${workerName}.js`, { type: 'module' })

// ok: no-dynamic-worker-body
const r = new Worker(`${STATIC_BASE}/decompressionWorker.js`, { type: 'module' })

const interpolatedPath = `/static/workers/${workerName}.js`
// ok: no-dynamic-worker-body
const s = new Worker(interpolatedPath, { type: 'module' })

// Only the URL argument counts. A blob URL somewhere else in the call is not the worker
// body.
// ok: no-dynamic-worker-body
const t = new Worker('/static/decompressionWorker.js', { name: URL.createObjectURL(debugBlob) })

// Object URLs for downloads and previews are untouched: nothing runs them as code.
// ok: no-dynamic-worker-body
const j = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
