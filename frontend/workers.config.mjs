// The web workers the app loads from /static at runtime, in one place so the production build
// (build.mjs) and the dev watcher (bin/watch-workers.mjs) cannot drift. Vite serves the app in
// dev but does not build these, so without the watcher they are simply absent locally and every
// worker silently falls back to the main thread.
export const WORKER_ENTRIES = [
    {
        name: 'Decompression Worker',
        entryPoint: 'src/scenes/session-recordings/player/snapshot-processing/decompressionWorker.ts',
        outfileName: 'decompressionWorker.js',
    },
    {
        name: 'HogQL Parser Worker',
        entryPoint: 'src/scenes/data-warehouse/editor/hogqlParserWorker.ts',
        outfileName: 'hogqlParserWorker.js',
    },
    {
        name: 'Monaco Editor Worker',
        entryPoint: 'src/lib/monaco/workers/editor.worker.ts',
        outfileName: 'monacoEditorWorker.js',
    },
    {
        name: 'Monaco JSON Worker',
        entryPoint: 'src/lib/monaco/workers/json.worker.ts',
        outfileName: 'monacoJsonWorker.js',
    },
    {
        name: 'Monaco TypeScript Worker',
        entryPoint: 'src/lib/monaco/workers/ts.worker.ts',
        outfileName: 'monacoTsWorker.js',
    },
]
