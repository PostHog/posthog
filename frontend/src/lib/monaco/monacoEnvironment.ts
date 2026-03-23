// Configure Monaco Editor to use bundled web workers served from /static/
// instead of trying to load them from a CDN or different origin.
// This prevents cross-origin errors with json.worker.js and other language workers.
self.MonacoEnvironment = {
    getWorkerUrl(_moduleId: string, label: string): string {
        if (label === 'json') {
            return '/static/monacoJsonWorker.js'
        }
        if (label === 'typescript' || label === 'javascript') {
            return '/static/monacoTsWorker.js'
        }
        return '/static/monacoEditorWorker.js'
    },
}
