import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { updateViewLabel } from 'scenes/data-warehouse/editor/updateViewLabel'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailQueryEditorActions({ id }: { id: string }): JSX.Element | null {
    const { queryEditorState, effectiveTab } = useValues(nodeDetailSceneLogic({ id }))
    const { discardQueryEditorChanges, updateViewFromQueryEditor } = useActions(nodeDetailSceneLogic({ id }))

    // Nothing to save means nothing to offer: the save bar over the editor carries both actions
    // once an edit exists, so an always-present pair of disabled buttons here is just noise.
    if (!queryEditorState || effectiveTab !== 'query' || !queryEditorState.hasChanges) {
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
                {updateViewLabel(queryEditorState.isMaterializedView)}
            </LemonButton>
        </>
    )
}
