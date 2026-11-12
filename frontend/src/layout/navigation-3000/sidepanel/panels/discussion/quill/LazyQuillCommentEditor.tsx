import { Suspense } from 'react'

import { Skeleton } from '@posthog/quill'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { QuillCommentEditorProps } from './QuillCommentEditor'

// The editor pulls in the rich text stack, which stays off the eager path of every scene with a discussion.
const QuillCommentEditor = lazyWithRetry(() =>
    import('./QuillCommentEditor').then((module) => ({ default: module.QuillCommentEditor }))
)

/** `QuillCommentEditor` loaded on first render. A placeholder of the editor's height holds its place meanwhile. */
export function LazyQuillCommentEditor(props: QuillCommentEditorProps): JSX.Element {
    return (
        <Suspense fallback={<Skeleton className="h-24" aria-busy />}>
            <QuillCommentEditor {...props} />
        </Suspense>
    )
}
