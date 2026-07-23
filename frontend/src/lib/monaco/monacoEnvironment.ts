// Configure Monaco Editor to use bundled web workers served from /static/
// instead of trying to load them from a CDN or different origin.
// This prevents cross-origin errors with json.worker.js and other language workers.

import { loader } from '@monaco-editor/react'
import * as monacoModule from 'monaco-editor'

// Each worker ships as a module (ESM) build and a classic (IIFE) build. We prefer the module
// worker, but some older browsers don't support `new Worker(url, { type: 'module' })` and throw
// synchronously. Rather than re-throwing — which drops Monaco into its main-thread fallback and
// surfaces a benign but noisy `Error: Unexpected usage` while disabling language services — we
// fall back to the classic worker, which is supported everywhere Monaco runs.
function createWorker(moduleUrl: string, classicUrl: string): Worker {
    try {
        return new Worker(moduleUrl, { type: 'module' })
    } catch {
        try {
            return new Worker(classicUrl)
        } catch (e) {
            // Both builds failed to instantiate (e.g. the static asset 404s transiently during a
            // deploy). Monaco will fall back to running the worker on the main thread; the
            // resulting `Unexpected usage` exception is dropped from error tracking by the central
            // before_send filter (see selfReadOnlyModeLogic.dropBenignExceptions).
            if (process.env.NODE_ENV === 'development') {
                console.error(
                    `Monaco worker failed to load from ${moduleUrl} and ${classicUrl}. ` +
                        'In development, ensure Django is running and workers are built. ' +
                        'Run: node frontend/build.mjs'
                )
            }
            throw e
        }
    }
}

globalThis.MonacoEnvironment = {
    getWorker(_moduleId: string, label: string): Worker {
        if (label === 'json') {
            return createWorker('/static/monacoJsonWorker.js', '/static/monacoJsonWorker.classic.js')
        }
        if (label === 'typescript' || label === 'javascript') {
            return createWorker('/static/monacoTsWorker.js', '/static/monacoTsWorker.classic.js')
        }
        return createWorker('/static/monacoEditorWorker.js', '/static/monacoEditorWorker.classic.js')
    },
}

// Point @monaco-editor/react at the bundled monaco-editor module so its components
// don't race to fetch a different Monaco build (and its workerMain.js) from jsdelivr.
// Must run before any @monaco-editor/react component instantiates, so this side-effect
// lives here rather than inside CodeEditor.tsx (which only loads when CodeEditor mounts).
if (loader) {
    loader.config({ monaco: monacoModule })
}
