import { Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/lazyWithRetry'

import type { CodeEditorProps } from './CodeEditorImpl'

export type { CodeEditorProps } from './CodeEditorImpl'
export { clearLogicReference, initModel } from './modelLogicReference'

const LazyCodeEditor = lazyWithRetry(() => import('./CodeEditorImpl').then((m) => ({ default: m.CodeEditor })))

/** Lazy facade so importing CodeEditor doesn't pull monaco (~4 MB) into the importer's chunk. */
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
