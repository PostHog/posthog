import { Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { useRetryableLazy } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import type { CodeEditorProps } from './CodeEditorImpl'
import { CodeEditorLoadError } from './CodeEditorLoadError'

export type { CodeEditorProps } from './CodeEditorImpl'
export { clearLogicReference, initModel } from './modelLogicReference'

/** Lazy facade so importing CodeEditor doesn't pull monaco (~4 MB) into the importer's chunk. */
export function CodeEditor(props: CodeEditorProps): JSX.Element {
    const { Lazy, retry } = useRetryableLazy(() => import('./CodeEditorImpl').then((m) => ({ default: m.CodeEditor })))

    return (
        // The editor is one field on a page the person is working in, so its chunk failing must not
        // reload them out of an edit they have not saved. It degrades to a retry in place instead.
        <ChunkLoadErrorBoundary
            degradeInPlace
            fallback={(error, clearError) => (
                <CodeEditorLoadError
                    error={error}
                    onRetry={() => {
                        retry()
                        clearError()
                    }}
                />
            )}
        >
            <Suspense
                fallback={
                    <div className="CodeEditor relative h-full w-full">
                        <Spinner />
                    </div>
                }
            >
                <Lazy {...props} />
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}
