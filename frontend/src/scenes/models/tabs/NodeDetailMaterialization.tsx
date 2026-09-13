import { useActions, useValues } from 'kea'

import * as doctor from '@posthog/brand/hoggies/png/doctor-1'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { MaterializationStatusPanel } from 'scenes/data-warehouse/saved_queries/MaterializationStatusPanel'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

const HedgehogDoctor = pngHoggie(doctor)

export function NodeDetailMaterialization({ id }: { id: string }): JSX.Element | null {
    const { node, savedQuery, savedQueryError, savedQueryLoading } = useValues(nodeDetailSceneLogic({ id }))
    const { loadSavedQuery } = useActions(nodeDetailSceneLogic({ id }))

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
                    <LemonButton type="secondary" onClick={loadSavedQuery} loading={savedQueryLoading}>
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
