import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { useDiscardEditingView } from 'scenes/data-warehouse/editor/useDiscardEditingView'
import { useUpdateEditingView } from 'scenes/data-warehouse/editor/useUpdateEditingView'

import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'

export function NodeDetailQueryEditorSync({ id }: { id: string }): null {
    const { disabledReason, loading, isMaterializedView } = useUpdateEditingView()
    const { disabledReason: discardDisabledReason } = useDiscardEditingView()
    const { hasEditorChanges } = useValues(sqlEditorLogic)
    const { setQueryEditorState } = useActions(nodeDetailSceneLogic({ id }))

    useEffect(() => {
        setQueryEditorState({
            updateDisabledReason: disabledReason,
            updateLoading: loading,
            discardDisabledReason,
            isMaterializedView,
            hasChanges: hasEditorChanges,
        })
    }, [disabledReason, loading, discardDisabledReason, isMaterializedView, hasEditorChanges, setQueryEditorState])

    useOnMountEffect(() => () => setQueryEditorState(null))

    return null
}
