import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { QueryBasedInsightModel } from '~/types'

export function NotebookActionButton({ insight }: { insight: QueryBasedInsightModel }): JSX.Element {
    const { addSavedInsightToNotebook } = useActions(notebookLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            fullWidth
            onClick={(e) => {
                e.preventDefault()
                addSavedInsightToNotebook(insight.short_id)
            }}
            icon={<IconPlusSmall />}
        />
    )
}
