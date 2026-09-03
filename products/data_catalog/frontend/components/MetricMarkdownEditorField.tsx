import { Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'

import type { MetricMarkdownEditorProps } from './MetricMarkdownEditor'

// TipTap and the converter are a heavy chunk; load them only once a definition is being edited.
// The round-trip-safety check also lives inside the lazy module for the same reason.
const LazyMetricMarkdownEditor = lazyWithRetry(() =>
    import('./MetricMarkdownEditor').then((m) => ({ default: m.MetricMarkdownEditor }))
)

export function MetricMarkdownEditorField(props: MetricMarkdownEditorProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div
                    className="flex min-h-[12rem] w-full items-center justify-center rounded border border-primary bg-surface-secondary"
                    aria-busy
                    data-attr="data-catalog-metric-markdown-editor-suspense-fallback"
                >
                    <Spinner className="text-2xl" />
                </div>
            }
        >
            <LazyMetricMarkdownEditor {...props} />
        </Suspense>
    )
}
