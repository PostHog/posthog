import { useActions, useValues } from 'kea'

import * as doctor from '@posthog/brand/hoggies/png/doctor-1'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { materializationJobsLogic } from 'scenes/data-warehouse/saved_queries/materializationJobsLogic'
import { MaterializationStatusPanel } from 'scenes/data-warehouse/saved_queries/MaterializationStatusPanel'

import { MaterializationLoading } from 'products/data_warehouse/frontend/shared/components/MaterializationLoading'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

const HedgehogDoctor = pngHoggie(doctor)

export function NodeDetailMaterialization({ id }: { id: string }): JSX.Element | null {
    const { node, savedQuery, savedQueryError, savedQueryLoading } = useValues(nodeDetailSceneLogic({ id }))
    const { loadSavedQuery } = useActions(nodeDetailSceneLogic({ id }))
    const { loadSavedQuery: reloadPanelSavedQuery, loadDataModelingJobs } = useActions(
        materializationJobsLogic({
            viewId: node?.saved_query_id ?? '',
            kind: node?.type === 'endpoint' ? 'endpoint' : 'view',
        })
    )

    const retry = (): void => {
        loadSavedQuery()
        // The panel below holds its own copy of the settings and the run history, and its logic
        // stays mounted for the whole scene, so remounting the panel refetches neither.
        if (node?.saved_query_id) {
            reloadPanelSavedQuery()
            loadDataModelingJobs()
        }
    }

    // Clicking retry clears the error before the request settles, so without this the tab would go
    // blank for the length of the request.
    if (savedQueryLoading && !savedQuery) {
        return <MaterializationLoading />
    }

    if (savedQueryError) {
        return (
            <ProductIntroduction
                thingName="materialization settings"
                titleOverride="Couldn't load materialization settings"
                description="Try again to load this model's refresh settings and run history."
                customHog={HedgehogDoctor}
                hogLayout="responsive"
                useMainContentContainerQueries
                hogClassName="w-32 sm:w-32 lg:w-32 mb-0"
                className="border-solid border rounded-lg my-0"
                actionElementOverride={
                    <LemonButton type="secondary" onClick={retry} loading={savedQueryLoading}>
                        Retry
                    </LemonButton>
                }
            />
        )
    }

    if (!savedQuery) {
        return null
    }

    return (
        <div className="flex flex-col gap-3">
            <div>
                <h3 className="mb-1">Materialization</h3>
                <p className="text-secondary mb-0">
                    Store this model's query results and refresh them on a schedule so other queries can use them.
                </p>
            </div>
            <MaterializationStatusPanel
                viewId={savedQuery.id}
                kind={node?.type === 'endpoint' ? 'endpoint' : 'view'}
                hideTitle
                showRunActions={false}
                showStatusSummary={false}
            />
        </div>
    )
}
