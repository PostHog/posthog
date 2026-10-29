import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function QuillNodeDetailQueryEditorActions({ id }: { id: string }): JSX.Element | null {
    const { queryEditorState, effectiveTab } = useValues(nodeDetailSceneLogic({ id }))
    const { discardQueryEditorChanges, updateViewFromQueryEditor } = useActions(nodeDetailSceneLogic({ id }))

    if (!queryEditorState || effectiveTab !== 'query') {
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
                {queryEditorState.isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
            </Button>
        </>
    )
}
