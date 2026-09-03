import monacoStylesheetUrl from './monacoStylesheet.css?url'

import { Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { loadStylesheet } from 'lib/utils/lazyStylesheet'
import { lazyWithRetry } from 'lib/utils/retryImport'

import type { CodeEditorProps } from './CodeEditorImpl'

export type { CodeEditorProps } from './CodeEditorImpl'
export { clearLogicReference, initModel } from './modelLogicReference'

const LazyCodeEditor = lazyWithRetry(() =>
    Promise.all([import('./CodeEditorImpl'), loadStylesheet(monacoStylesheetUrl)]).then(([m]) => ({
        default: m.CodeEditor,
    }))
)

/** Lazy facade so importing CodeEditor doesn't pull monaco (~4 MB) or its CSS into the importer's chunk. */
export function CodeEditor(props: CodeEditorProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div className="CodeEditor relative h-full w-full">
                    <Spinner />
                </div>
            }
        >
            <LazyCodeEditor {...props} />
        </Suspense>
    )
}
