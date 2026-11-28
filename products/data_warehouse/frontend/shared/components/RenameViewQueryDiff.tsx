import { Suspense } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/retryImport'

const MonacoDiffEditor = lazyWithRetry(() => import('lib/components/MonacoDiffEditor'))

export function RenameViewQueryDiff({ before, after }: { before: string; after: string }): JSX.Element {
    return (
        <Suspense fallback={<Spinner className="text-2xl mx-auto my-4" />}>
            <MonacoDiffEditor
                original={before}
                modified={after}
                language="sql"
                options={{
                    renderSideBySide: false,
                    renderOverviewRuler: false,
                    scrollBeyondLastLine: false,
                    hideUnchangedRegions: { enabled: true, contextLineCount: 2, minimumLineCount: 3 },
                }}
            />
        </Suspense>
    )
}
