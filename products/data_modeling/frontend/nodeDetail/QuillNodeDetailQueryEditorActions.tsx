import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { updateViewLabel } from 'scenes/data-warehouse/editor/updateViewLabel'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function QuillNodeDetailQueryEditorActions({ id }: { id: string }): JSX.Element | null {
    const { queryEditorState, effectiveTab } = useValues(nodeDetailSceneLogic({ id }))
    const { discardQueryEditorChanges, updateViewFromQueryEditor } = useActions(nodeDetailSceneLogic({ id }))

    // Nothing to save means nothing to offer: the save bar over the editor carries both actions
    // once an edit exists, so an always-present pair of disabled buttons here is just noise.
    if (!queryEditorState || effectiveTab !== 'query' || !queryEditorState.hasChanges) {
        return null
    }

    return (
        <>
            <Button
                variant="outline"
                onClick={() => discardQueryEditorChanges()}
                disabledReason={queryEditorState.discardDisabledReason}
                data-attr="node-detail-discard-changes"
            >
                Discard changes
            </Button>
            <Button
                variant="primary"
                onClick={() => updateViewFromQueryEditor()}
                disabledReason={queryEditorState.updateDisabledReason}
                loading={queryEditorState.updateLoading}
                data-attr="node-detail-update-view"
            >
                {updateViewLabel(queryEditorState.isMaterializedView)}
            </Button>
        </>
    )
}
