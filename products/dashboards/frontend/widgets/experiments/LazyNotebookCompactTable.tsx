import { Suspense } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { lazyWithRetry } from 'lib/utils/lazyWithRetry'

import type { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'

type NotebookCompactTableProps = {
    result: NewExperimentQueryResponse
    metric: ExperimentMetric
}

// Lazy facade: the real table reuses the experiments scene (experimentLogic, featureFlagLogic, luxon,
// cron-parser) — ~1.5 MiB. A static import would pull all of that into the always-loaded dashboard
// graph; behind a dynamic import it loads only when a results widget actually renders.
const LazyTable = lazyWithRetry(() =>
    import('scenes/experiments/notebook/NotebookCompactTable').then((module) => ({
        default: module.NotebookCompactTable,
    }))
)

export function NotebookCompactTable(props: NotebookCompactTableProps): JSX.Element {
    return (
        <Suspense fallback={<LemonSkeleton className="h-16 w-full" />}>
            <LazyTable {...props} />
        </Suspense>
    )
}
