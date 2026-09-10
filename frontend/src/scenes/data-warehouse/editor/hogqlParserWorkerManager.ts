import { type AstRange, innermostSelectRangeFromAst, tablesAndColumnsFromAst } from './hogqlAst'
import { parseSelect } from './hogqlParserSingleton'
import type { HogqlParserQuestion, HogqlParserRequest, HogqlParserResponse } from './hogqlParserWorker'

// Runs the HogQL parse in a worker so a long query does not freeze the editor. Falls back to
// parsing on the main thread whenever the worker is unavailable — no Worker (jsdom), the bundle
// isn't served, init times out, or a request fails. The fallback is slow but correct, and it runs
// the same walkers as the worker, so behavior does not change with it.

const WORKER_URL = '/static/hogqlParserWorker.js'
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
        const created = new Worker(WORKER_URL, { type: 'module' })
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

async function ask(request: HogqlParserQuestion): Promise<any> {
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

/** Parse on the main thread. Blocks, so it is only for when the worker cannot be used. */
async function parseOnMainThread(query: string): Promise<any | null> {
    try {
        return JSON.parse(await parseSelect(query))
    } catch {
        return null
    }
}

export async function analyzeInnermostSelect(query: string, localOffset: number): Promise<AstRange | null> {
    if (!workerUnavailable) {
        try {
            return await ask({ op: 'innermostSelect', query, localOffset })
        } catch {
            // fall through to the main thread
        }
    }
    const ast = await parseOnMainThread(query)
    return ast ? innermostSelectRangeFromAst(ast, localOffset) : null
}

export async function analyzeTablesAndColumns(query: string): Promise<Record<string, Record<string, boolean>>> {
    if (!workerUnavailable) {
        try {
            return await ask({ op: 'tablesAndColumns', query })
        } catch {
            // fall through to the main thread
        }
    }
    const ast = await parseOnMainThread(query)
    return ast ? tablesAndColumnsFromAst(ast) : {}
}
