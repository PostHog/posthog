import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailQueryEditorActions({ id }: { id: string }): JSX.Element | null {
    const { queryEditorState, effectiveTab } = useValues(nodeDetailSceneLogic({ id }))
    const { discardQueryEditorChanges, updateViewFromQueryEditor } = useActions(nodeDetailSceneLogic({ id }))

    if (!queryEditorState || effectiveTab !== 'query') {
        return null
    }

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => discardQueryEditorChanges()}
                disabledReason={queryEditorState.discardDisabledReason}
                data-attr="node-detail-discard-changes"
            >
                Discard changes
            </LemonButton>
            <LemonButton
                type="primary"
                size="small"
                onClick={() => updateViewFromQueryEditor()}
                disabledReason={queryEditorState.updateDisabledReason}
                loading={queryEditorState.updateLoading}
                data-attr="node-detail-update-view"
            >
                {queryEditorState.isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
            </LemonButton>
        </>
    )
}
