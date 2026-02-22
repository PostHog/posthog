// Configure Monaco's web worker environment globally.
// Workers offload language parsing/validation (JSON, TypeScript) from the main thread.
// Import this module before creating any Monaco editors.
globalThis.MonacoEnvironment = {
    getWorker(_workerId: string, label: string) {
        if (label === 'json') {
            return new Worker('/static/monacoJsonWorker.js', { type: 'module' })
        }
        if (label === 'typescript' || label === 'javascript') {
            return new Worker('/static/monacoTsWorker.js', { type: 'module' })
        }
        return new Worker('/static/monacoEditorWorker.js', { type: 'module' })
    },
}
