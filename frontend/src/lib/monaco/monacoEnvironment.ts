// Configure Monaco Editor to use bundled web workers served from /static/
// instead of trying to load them from a CDN or different origin.
// This prevents cross-origin errors with json.worker.js and other language workers.

import { loader } from '@monaco-editor/react'
import * as monacoModule from 'monaco-editor'

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

// Point @monaco-editor/react at the bundled monaco-editor module so its components
// don't race to fetch a different Monaco build (and its workerMain.js) from jsdelivr.
// Must run before any @monaco-editor/react component instantiates, so this side-effect
// lives here rather than inside CodeEditor.tsx (which only loads when CodeEditor mounts).
if (loader) {
    loader.config({ monaco: monacoModule })
}
