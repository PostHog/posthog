import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { QueryBasedInsightModel } from '~/types'

export function NotebookActionButton({ insight }: { insight: QueryBasedInsightModel }): JSX.Element {
    const { addSavedInsightToNotebook } = useActions(notebookLogic)
    const { insightShortIdsInNotebook } = useValues(notebookLogic)
    const isInNotebook = !!insightShortIdsInNotebook?.includes(insight.short_id)

    return (
        <LemonButton
            type="secondary"
            size="small"
            fullWidth
            disabledReason={isInNotebook ? 'Insight already in notebook' : ''}
            onClick={(e) => {
                e.preventDefault()
                if (!isInNotebook) {
                    addSavedInsightToNotebook(insight.short_id)
                }
            }}
            icon={<IconPlusSmall />}
        />
    )
}
