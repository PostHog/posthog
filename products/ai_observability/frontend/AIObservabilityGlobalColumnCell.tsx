import { ComponentProps, Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { QueryContextColumnComponent } from '~/queries/types'

type CellProps = ComponentProps<QueryContextColumnComponent> & { rendererKey: string }

const RendererCell = lazyWithRetry(() =>
    import('./aiObservabilityColumnRenderers').then(({ aiObservabilityColumnRenderers }) => ({
        default: function RendererCell({ rendererKey, ...props }: CellProps): JSX.Element | null {
            const Render = aiObservabilityColumnRenderers[rendererKey]?.render
            return Render ? <Render {...props} /> : null
        },
    }))
)

export function AIObservabilityGlobalColumnCell(props: CellProps): JSX.Element {
    return (
        // The query's own ErrorBoundary is nearer than the scene's, so without this a stale chunk never reloads.
        <ChunkLoadErrorBoundary>
            <Suspense fallback={<Spinner />}>
                <RendererCell {...props} />
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}
