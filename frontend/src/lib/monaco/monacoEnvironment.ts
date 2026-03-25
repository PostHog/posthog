// Configure Monaco Editor to use bundled web workers served from /static/
// instead of trying to load them from a CDN or different origin.
// This prevents cross-origin errors with json.worker.js and other language workers.

function createWorker(path: string): Worker {
    try {
        return new Worker(path, { type: 'module' })
    } catch (e) {
        console.error(
            `Monaco worker failed to load from ${path}. ` +
                'In development, ensure Django is running and workers are built. ' +
                'Run: node frontend/build.mjs'
        )
        throw e
    }
}

globalThis.MonacoEnvironment = {
    getWorker(_moduleId: string, label: string): Worker {
        if (label === 'json') {
            return createWorker('/static/monacoJsonWorker.js')
        }
        if (label === 'typescript' || label === 'javascript') {
            return createWorker('/static/monacoTsWorker.js')
        }
        return createWorker('/static/monacoEditorWorker.js')
    },
}
