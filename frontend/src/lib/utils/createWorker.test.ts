import { createWorker } from 'lib/utils/createWorker'

class FakeWorker extends EventTarget {
    constructor(readonly url: string) {
        super()
    }
}

function urlOf(worker: Worker): string {
    return (worker as unknown as FakeWorker).url
}

describe('createWorker', () => {
    const globals = globalThis as unknown as {
        Worker?: typeof Worker
        __POSTHOG_WORKER_FILES__?: Record<string, string>
    }
    const originalWorker = globals.Worker

    beforeEach(() => {
        globals.Worker = FakeWorker as unknown as typeof Worker
        globals.__POSTHOG_WORKER_FILES__ = { 'answered.js': 'answered-HASH.js', 'missing.js': 'missing-HASH.js' }
    })

    afterEach(() => {
        globals.Worker = originalWorker
        delete globals.__POSTHOG_WORKER_FILES__
    })

    it('loads the fixed name when the build defines no hashed names', () => {
        delete globals.__POSTHOG_WORKER_FILES__

        expect(urlOf(createWorker('missing.js', { type: 'module' }))).toBe('/static/missing.js')
    })

    it('loads the fixed name after the hashed file fails to load', () => {
        const first = createWorker('missing.js', { type: 'module' })
        expect(urlOf(first)).toBe('/static/missing-HASH.js')

        first.dispatchEvent(new Event('error'))

        expect(urlOf(createWorker('missing.js', { type: 'module' }))).toBe('/static/missing.js')
    })

    it('keeps the hashed name when the worker fails after it answered', () => {
        const first = createWorker('answered.js', { type: 'module' })

        first.dispatchEvent(new MessageEvent('message', { data: { type: 'ready' } }))
        first.dispatchEvent(new Event('error'))

        expect(urlOf(createWorker('answered.js', { type: 'module' }))).toBe('/static/answered-HASH.js')
    })
})
