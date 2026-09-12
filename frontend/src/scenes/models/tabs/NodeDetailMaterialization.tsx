import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { MaterializationStatusPanel } from 'scenes/data-warehouse/saved_queries/MaterializationStatusPanel'

import { nodeDetailSceneLogic } from '../nodeDetailSceneLogic'

export function NodeDetailMaterialization({ id }: { id: string }): JSX.Element | null {
    const { node, savedQuery, savedQueryError, savedQueryMissing } = useValues(nodeDetailSceneLogic({ id }))
    const { loadSavedQuery } = useActions(nodeDetailSceneLogic({ id }))

    if (savedQueryError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadSavedQuery }}>
                Couldn't load this model's materialization settings.
            </LemonBanner>
        )
    }

    if (savedQueryMissing) {
        return (
            <LemonBanner type="warning">
                This model's query is no longer available, so it has no materialization settings.
            </LemonBanner>
        )
    }

    if (!savedQuery) {
        return null
    }

    return (
        <MaterializationStatusPanel
            viewId={savedQuery.id}
            kind={node?.type === 'endpoint' ? 'endpoint' : 'view'}
            hideTitle
        />
    )
}
