import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { savedDashboardLogic } from './savedDashboardLogic'

const LABELS = {
    saved: 'Saved',
    unsaved: 'Unsaved changes',
    saving: 'Saving…',
}

export function SaveStatus(): JSX.Element | null {
    const { saveState } = useValues(savedDashboardLogic)
    const { saveBoard } = useActions(savedDashboardLogic)
    // Without a board there is nothing to save, such as the fixture shown at `/dashboard-v2`.
    if (!saveState || saveState === 'conflict') {
        return null
    }
    if (saveState === 'failed') {
        return (
            <span className="flex items-center gap-1 text-sm text-destructive-foreground">
                Couldn't save your changes.
                <Button size="sm" variant="outline" onClick={saveBoard} data-attr="dashboard-v2-save-retry">
                    Retry
                </Button>
            </span>
        )
    }
    return (
        <span role="status" className="text-sm text-muted-foreground">
            {LABELS[saveState]}
        </span>
    )
}
