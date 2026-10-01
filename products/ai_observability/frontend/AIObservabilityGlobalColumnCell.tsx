import { ComponentProps, Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { QueryContextColumnComponent } from '~/queries/types'

type CellProps = ComponentProps<QueryContextColumnComponent>

const RendererCell = lazyWithRetry(() =>
    import('./aiObservabilityColumnRenderers').then(({ aiObservabilityColumnRenderers }) => ({
        default: function RendererCell(props: CellProps): JSX.Element | null {
            const Render = aiObservabilityColumnRenderers[props.columnName]?.render
            return Render ? <Render {...props} /> : null
        },
    }))
)

export function AIObservabilityGlobalColumnCell(props: CellProps): JSX.Element {
    return (
        <Suspense fallback={<Spinner />}>
            <RendererCell {...props} />
        </Suspense>
    )
}
