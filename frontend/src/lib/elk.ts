import { type ELK } from 'elkjs'

// Falls back to the main thread without a Worker (jsdom) or when the bundle isn't served (Vite dev)
const WORKER_URL = '/static/elkWorker.js'
const WORKER_PROBE_TIMEOUT_MS = 5000

let elkPromise: Promise<ELK> | null = null

async function loadBundledElk(): Promise<ELK> {
    const { default: ELKConstructor } = await import('elkjs/lib/elk.bundled.js')
    return new ELKConstructor()
}

async function loadWorkerElk(): Promise<ELK> {
    if (typeof Worker === 'undefined') {
        throw new Error('Worker is not available')
    }
    const { default: ELKConstructor } = await import('elkjs/lib/elk-api.js')
    let worker: Worker | null = null
    const elk = new ELKConstructor({
        workerFactory: () => {
            worker = new Worker(WORKER_URL, { type: 'module' })
            return worker
        },
    })
    // elk-api never rejects when the worker script fails to load, so a layout would hang forever, so check the worker answers first
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        await Promise.race([
            elk.layout({ id: 'probe', children: [] }),
            new Promise<never>((_, reject) => {
                timer = setTimeout(() => reject(new Error('ELK worker did not answer')), WORKER_PROBE_TIMEOUT_MS)
                worker?.addEventListener('error', () => reject(new Error('ELK worker failed to load')))
            }),
        ])
    } catch (error) {
        elk.terminateWorker()
        throw error
    } finally {
        clearTimeout(timer)
    }
    return elk
}

export function getElk(): Promise<ELK> {
    if (!elkPromise) {
        elkPromise = loadWorkerElk().catch(() => loadBundledElk())
    }
    return elkPromise
}
