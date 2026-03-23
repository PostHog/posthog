// Configure Monaco Editor to use bundled web workers served from /static/
// instead of trying to load them from a CDN or different origin.
// This prevents cross-origin errors with json.worker.js and other language workers.
self.MonacoEnvironment = {
    getWorker(_moduleId: string, label: string): Worker {
        if (label === 'json') {
            return new Worker('/static/monacoJsonWorker.js', { type: 'module' })
        }
        if (label === 'typescript' || label === 'javascript') {
            return new Worker('/static/monacoTsWorker.js', { type: 'module' })
        }
        return new Worker('/static/monacoEditorWorker.js', { type: 'module' })
    },
}
