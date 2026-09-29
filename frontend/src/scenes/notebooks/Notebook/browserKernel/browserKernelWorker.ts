// A notebook's Python kernel, running Pyodide in a web worker so user code never blocks the page.
import type {
    BrowserKernelEnvelope,
    BrowserKernelRequest,
    BrowserKernelResponse,
    BrowserKernelStagedInput,
} from './browserKernelProtocol'
import { BROWSER_KERNEL_SESSION_SOURCE } from './browserKernelSessionSource'

type PyProxy = { destroy: () => void } & Record<string, any>

type Pyodide = {
    runPythonAsync: (code: string) => Promise<any>
    runPython: (code: string) => any
    loadPackage: (packages: string[], options?: { messageCallback?: (message: string) => void }) => Promise<void>
    loadPackagesFromImports: (code: string, options?: { messageCallback?: (message: string) => void }) => Promise<void>
    setInterruptBuffer: (buffer: Uint8Array) => void
    globals: { get: (name: string) => PyProxy }
    toPy: (value: unknown) => PyProxy
}

type LoadPyodide = (options: {
    indexURL: string
    env?: Record<string, string>
    stdout?: (text: string) => void
    stderr?: (text: string) => void
}) => Promise<Pyodide>

let pyodide: Pyodide | null = null
let session: PyProxy | null = null
let interruptView: Uint8Array | null = null

function post(message: BrowserKernelResponse): void {
    postMessage(message)
}

function progress(message: string): void {
    post({ type: 'progress', message })
}

async function init(indexURL: string, packages: string[], interruptBuffer: SharedArrayBuffer | null): Promise<null> {
    progress('Downloading Python')
    // A module worker cannot importScripts, and the loader must come from the same release as
    // the wasm and wheels it fetches next, so it is imported from the pinned CDN path.
    const module = (await import(/* @vite-ignore */ `${indexURL}pyodide.mjs`)) as { loadPyodide: LoadPyodide }
    const instance = await module.loadPyodide({
        indexURL,
        // Figures render headless: plt.show() is a no-op and the session collects open figures.
        env: { MPLBACKEND: 'Agg', HOME: '/home/pyodide' },
    })
    progress('Loading pandas and DuckDB')
    await instance.loadPackage(packages, { messageCallback: () => {} })
    await instance.runPythonAsync(BROWSER_KERNEL_SESSION_SOURCE)
    if (interruptBuffer) {
        interruptView = new Uint8Array(interruptBuffer)
        instance.setInterruptBuffer(interruptView)
    }
    pyodide = instance
    session = instance.globals.get('_ph_browser')
    return null
}

function requireSession(): { pyodide: Pyodide; session: PyProxy } {
    if (!pyodide || !session) {
        throw new Error('The browser kernel is not running.')
    }
    return { pyodide, session }
}

async function run(
    payload: Extract<BrowserKernelRequest, { type: 'run' }>['payload'],
    staged: BrowserKernelStagedInput[]
): Promise<BrowserKernelEnvelope> {
    const { pyodide, session } = requireSession()
    for (const input of staged) {
        const columns = pyodide.toPy(input.columns)
        const types = pyodide.toPy(input.types)
        const values = pyodide.toPy(input.values)
        try {
            session.stage_input(input.key, columns, types, values)
        } finally {
            columns.destroy()
            types.destroy()
            values.destroy()
        }
    }
    if (payload.node_type === 'python') {
        await pyodide.loadPackagesFromImports(payload.code, {
            messageCallback: (message) => {
                if (message.startsWith('Loading ')) {
                    progress(message.replace(/\.$/, ''))
                }
            },
        })
    }
    if (interruptView) {
        interruptView[0] = 0
    }
    const pyPayload = pyodide.toPy(payload)
    try {
        return JSON.parse(await session.run_node(pyPayload)) as BrowserKernelEnvelope
    } finally {
        pyPayload.destroy()
    }
}

async function handle(request: BrowserKernelRequest): Promise<unknown> {
    switch (request.type) {
        case 'init':
            return await init(request.indexURL, request.packages, request.interruptBuffer)
        case 'run':
            return await run(request.payload, request.staged)
        case 'hasInput':
            return !!requireSession().session.has_input(request.key)
        case 'page':
            return JSON.parse(requireSession().session.page(request.resultId, request.offset, request.limit))
        case 'readFrame':
            return JSON.parse(requireSession().session.read_frame(request.name, request.offset, request.limit))
        case 'frames':
            return JSON.parse(requireSession().session.frames())
    }
}

// Requests run one at a time: a kernel has one namespace, and Pyodide is single-threaded anyway.
let queue: Promise<void> = Promise.resolve()

self.onmessage = ({ data }: MessageEvent<BrowserKernelRequest>): void => {
    queue = queue.then(async () => {
        try {
            post({ type: 'result', id: data.id, value: await handle(data) })
        } catch (error) {
            post({ type: 'error', id: data.id, message: error instanceof Error ? error.message : String(error) })
        }
    })
}
