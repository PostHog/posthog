// MSW v2 intercepts requests via spec-compliant fetch primitives that jsdom does
// not provide. Source them from undici (jsdom otherwise clobbers the Node globals)
// and assign before the test framework boots, so this must run first in setupFiles.
/* eslint-disable @typescript-eslint/no-require-imports */
const { TextEncoder, TextDecoder } = require('node:util')
const { ReadableStream, WritableStream, TransformStream } = require('node:stream/web')
const { Blob, File } = require('node:buffer')
const { BroadcastChannel, MessageChannel, MessagePort } = require('node:worker_threads')

// configurable so @mswjs/interceptors can wrap Request/Response when the server starts.
const define = (props) =>
    Object.defineProperties(
        globalThis,
        Object.fromEntries(
            Object.entries(props).map(([key, value]) => [key, { value, writable: true, configurable: true }])
        )
    )

// undici references TextEncoder/streams at module-eval time, so define these first.
define({
    TextEncoder,
    TextDecoder,
    ReadableStream,
    WritableStream,
    TransformStream,
    Blob,
    File,
    BroadcastChannel,
    MessageChannel,
    MessagePort,
})

// jsdom's setTimeout returns a number, but undici's internal fast-timer calls `.refresh()`/`.unref()`
// on the returned handle. Wrap jsdom's timer (so it still tears down with the window — Node's would
// leak past teardown) and expose a refreshable handle. Jest fake timers override these per-test.
const jsdomSetTimeout = globalThis.setTimeout
const jsdomClearTimeout = globalThis.clearTimeout
const handleId = (handle) => (handle && typeof handle === 'object' ? handle.__id : handle)
define({
    setTimeout: (callback, delay, ...args) => {
        const handle = {
            refresh() {
                jsdomClearTimeout(this.__id)
                this.__id = jsdomSetTimeout(callback, delay, ...args)
                return this
            },
            unref() {
                return this
            },
            ref() {
                return this
            },
            [Symbol.toPrimitive]() {
                return this.__id
            },
        }
        handle.__id = jsdomSetTimeout(callback, delay, ...args)
        return handle
    },
    clearTimeout: (handle) => jsdomClearTimeout(handleId(handle)),
})

// jsdom lacks setImmediate/clearImmediate, which undici needs. Node's setImmediate fires on the
// libuv check phase, which keeps running after jsdom tears down the window — and React 18's
// scheduler prefers setImmediate for performWorkUntilDeadline, so its render work lands
// post-teardown and throws "The `document` global ... is not defined anymore", crashing the whole
// file. Route it through the jsdom-bound setTimeout above so it tears down with the window instead.
define({
    setImmediate: (callback, ...args) => globalThis.setTimeout(callback, 0, ...args),
    clearImmediate: (handle) => globalThis.clearTimeout(handle),
})

// undici's fetch calls performance.markResourceTiming, which jsdom's performance lacks.
if (typeof globalThis.performance?.markResourceTiming !== 'function') {
    if (!globalThis.performance) {
        globalThis.performance = require('node:perf_hooks').performance
    }
    globalThis.performance.markResourceTiming = () => {}
}

const { fetch, Request, Response, Headers, FormData } = require('undici')

define({ fetch, Request, Response, Headers, FormData })
