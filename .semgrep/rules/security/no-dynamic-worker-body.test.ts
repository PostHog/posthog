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

// A same-origin file. This is the shape every first-party worker in the app uses, and it
// needs no blob: allowance.
// ok: no-dynamic-worker-body
const f = new Worker(new URL('./hogqlParser.worker.ts', import.meta.url), { type: 'module' })

// ok: no-dynamic-worker-body
const g = new Worker('/static/decompressionWorker.js', { type: 'module' })

// ok: no-dynamic-worker-body
const h = new Worker(WORKER_URL, { type: 'module' })

// A blob URL kept in a variable still reads as a file path here. The rule catches the
// inline construction, which is the shape that lets input reach a worker body.
// ok: no-dynamic-worker-body
const i = new Worker(precomputedUrl)

// Object URLs for downloads and previews are untouched: nothing runs them as code.
// ok: no-dynamic-worker-body
const j = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
