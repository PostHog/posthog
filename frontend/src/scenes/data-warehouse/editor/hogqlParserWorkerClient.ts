import { createWorker } from 'lib/utils/createWorker'

import type { HogqlParserQuestion, HogqlParserRequest, HogqlParserResponse } from './hogqlParserWorker'

// Talks to the parser worker and never imports the parser itself. The render-query bundle has no
// code splitting, so a path to `hogqlParserSingleton` would inline the parser WASM into it.

const READY_TIMEOUT_MS = 5000
const REQUEST_TIMEOUT_MS = 60000

interface Pending {
    resolve: (value: any) => void
    reject: (error: Error) => void
    timer: ReturnType<typeof setTimeout>
}

let worker: Worker | null = null
let workerReady: Promise<Worker> | null = null
let workerUnavailable = false
let nextId = 0
const pending = new Map<number, Pending>()

function failAllPending(error: Error): void {
    for (const [, entry] of pending) {
        clearTimeout(entry.timer)
        entry.reject(error)
    }
    pending.clear()
}

function teardown(): void {
    worker?.terminate()
    worker = null
    workerReady = null
    workerUnavailable = true
}

function getWorker(): Promise<Worker> {
    if (workerReady) {
        return workerReady
    }

    workerReady = new Promise<Worker>((resolve, reject) => {
        if (typeof Worker === 'undefined') {
            reject(new Error('Worker is not available'))
            return
        }
        const created = createWorker('hogqlParserWorker.js', { type: 'module' })
        worker = created

        const timer = setTimeout(() => reject(new Error('Parser worker init timed out')), READY_TIMEOUT_MS)

        created.addEventListener('message', (event: MessageEvent<HogqlParserResponse>) => {
            const data = event.data
            if ('type' in data && data.type === 'ready') {
                clearTimeout(timer)
                resolve(created)
                return
            }
            if (!('id' in data)) {
                return
            }
            const entry = pending.get(data.id)
            if (!entry) {
                return
            }
            pending.delete(data.id)
            clearTimeout(entry.timer)
            if ('error' in data) {
                entry.reject(new Error(data.error))
            } else {
                entry.resolve(data.result)
            }
        })

        created.addEventListener('error', (event) => {
            clearTimeout(timer)
            const error = new Error(`Parser worker error: ${event.message}`)
            reject(error)
            failAllPending(error)
            teardown()
        })
    }).catch((error) => {
        teardown()
        throw error
    })

    return workerReady
}

export async function askParserWorker(request: HogqlParserQuestion): Promise<any> {
    const active = await getWorker()
    const id = nextId++
    return await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            pending.delete(id)
            reject(new Error('Parser worker request timed out'))
        }, REQUEST_TIMEOUT_MS)
        pending.set(id, { resolve, reject, timer })
        active.postMessage({ ...request, id } as HogqlParserRequest)
    })
}

export function isParserWorkerUnavailable(): boolean {
    return workerUnavailable
}

// Hog parse time does not follow program size: a few hundred characters of nested `if` or chained
// `else if` take seconds. The no-return warning is advisory, so when the worker cannot answer it is
// skipped instead of parsing on the main thread.
export async function hogProgramCanFinishWithoutReturn(code: string): Promise<boolean> {
    if (workerUnavailable) {
        return false
    }
    try {
        return (await askParserWorker({ op: 'programCanFinishWithoutReturn', code })) === true
    } catch {
        return false
    }
}
