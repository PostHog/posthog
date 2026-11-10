import { useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { ProductEmptyStateGate } from 'lib/components/ProductEmptyState/ProductEmptyStateGate'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { evaluationsEmptyState } from '../emptyState/evaluationsEmptyState'
import { AIObservabilityEvaluationsScene } from './AIObservabilityEvaluationsScene'
import { evaluationsEntryLogic } from './evaluationsEntryLogic'
import { getEvaluationsEntryRedirect } from './evaluationsEntryRedirect'

export const scene: SceneExport = { component: EvaluationsScene, productKey: ProductKey.AI_OBSERVABILITY }

export function EvaluationsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    useMountedLogic(evaluationsEntryLogic)

    if (getEvaluationsEntryRedirect(searchParams)) {
        return <Spinner />
    }

    return (
        <ProductEmptyStateGate emptyState={evaluationsEmptyState}>
            <AIObservabilityEvaluationsScene />
        </ProductEmptyStateGate>
    )
}
