import { LemonButton } from '@posthog/lemon-ui'

import { useUpdateEditingView } from 'scenes/data-warehouse/editor/useUpdateEditingView'

export function NodeDetailUpdateViewButton(): JSX.Element {
    const { disabledReason, loading, isMaterializedView, update } = useUpdateEditingView()

    return (
        <LemonButton
            type="primary"
            size="small"
            onClick={update}
            disabledReason={disabledReason}
            loading={loading}
            data-attr="node-detail-update-view"
        >
            {isMaterializedView ? 'Update and re-materialize view' : 'Update view'}
        </LemonButton>
    )
}
