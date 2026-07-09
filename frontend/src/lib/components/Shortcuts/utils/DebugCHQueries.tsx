import { Suspense } from 'react'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/lazyWithRetry'

import type { DebugCHQueriesProps } from './DebugCHQueriesImpl'

const LazyDebugCHQueries = lazyWithRetry(() =>
    import('./DebugCHQueriesImpl').then((m) => ({ default: m.DebugCHQueries }))
)

/** Lazy facade so the debug panel's chart.js dependencies stay out of the eager menu/shortcut chunks. */
export function DebugCHQueries(props: DebugCHQueriesProps): JSX.Element {
    return (
        <Suspense fallback={<Spinner />}>
            <LazyDebugCHQueries {...props} />
        </Suspense>
    )
}

export function openCHQueriesDebugModal(): void {
    LemonDialog.open({
        title: 'ClickHouse queries recently executed for this user',
        content: <DebugCHQueries />,
        primaryButton: null,
        width: 1600,
    })
}
