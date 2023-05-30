import { NotebookLogicProps, notebookLogic } from './notebookLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { NotebookSyncStatus } from '~/types'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { IconDocumentExpand } from 'lib/lemon-ui/icons'
import { notebookSettingsLogic } from './notebookSettingsLogic'

const syncStatusMap: Record<NotebookSyncStatus, { content: React.ReactNode; tooltip: React.ReactNode }> = {
    synced: {
        content: 'Saved',
        tooltip: 'All changes are saved.',
    },
    saving: {
        content: (
            <>
                Saving <Spinner monocolor />
            </>
        ),
        tooltip: 'The changes are being saved to PostHog.',
    },
    unsaved: {
        content: 'Edited',
        tooltip:
            'You have made changes that are saved to your browser. These will be persisted to PostHog periodically.',
    },
    local: {
        content: 'Local',
        tooltip: 'This notebook is just stored in your browser.',
    },
}

export const NotebookSyncInfo = (props: NotebookLogicProps): JSX.Element | null => {
    const { syncStatus } = useValues(notebookLogic(props))
    const [shown, setShown] = useState(false)

    useEffect(() => {
        if (syncStatus !== 'synced') {
            return setShown(true)
        }

        if (shown === false) {
            return
        }

        const t = setTimeout(() => setShown(false), 3000)
        return () => clearTimeout(t)
    }, [syncStatus])

    if (!syncStatus) {
        return null
    }

    const content = syncStatusMap[syncStatus]

    return shown ? (
        <Tooltip title={content.tooltip}>
            <span className="flex items-center gap-1 text-muted-alt">{content.content}</span>
        </Tooltip>
    ) : null
}

export const NotebookExpandButton = (props: LemonButtonProps): JSX.Element => {
    const { isExpanded } = useValues(notebookSettingsLogic)
    const { setIsExpanded } = useActions(notebookSettingsLogic)

    return (
        <LemonButton
            {...props}
            onClick={() => setIsExpanded(!isExpanded)}
            icon={<IconDocumentExpand mode={isExpanded ? 'expand' : 'collapse'} />}
        />
    )
}
