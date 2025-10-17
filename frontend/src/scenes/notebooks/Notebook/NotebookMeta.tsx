import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconBook } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonTag } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconDocumentExpand } from 'lib/lemon-ui/icons'

import { NotebookSyncStatus } from '../types'
import { NotebookLogicProps, notebookLogic } from './notebookLogic'
import { notebookSettingsLogic } from './notebookSettingsLogic'

const syncStatusMap: Record<NotebookSyncStatus, { content: React.ReactNode; tooltip: React.ReactNode }> = {
    synced: {
        content: 'Saved',
        tooltip: 'All changes are saved.',
    },
    saving: {
        content: (
            <>
                Saving <Spinner textColored />
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
    const [debounceTimeout, setDebounceTimeout] = useState<NodeJS.Timeout | null>(null)
    const [debouncedSyncStatus, setDebouncedSyncStatus] = useState<NotebookSyncStatus | null>(null)

    const clearDebounceTimeout = useCallback(() => {
        if (debounceTimeout) {
            clearTimeout(debounceTimeout)
        }
    }, [debounceTimeout])

    useEffect(() => {
        clearDebounceTimeout()

        const debounceDelay = syncStatus === 'saving' ? 100 : 0
        const timeout = setTimeout(() => setDebouncedSyncStatus(syncStatus), debounceDelay)
        setDebounceTimeout(timeout)

        if (syncStatus !== 'synced') {
            return setShown(true)
        }

        if (shown === false) {
            return
        }

        const t = setTimeout(() => setShown(false), 3000)

        return () => {
            clearTimeout(t)
            clearDebounceTimeout()
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [syncStatus])

    if (!debouncedSyncStatus) {
        return null
    }

    const content = syncStatusMap[debouncedSyncStatus]

    return shown ? (
        <Tooltip title={content.tooltip} placement="left">
            <LemonTag className="uppercase select-none">{content.content}</LemonTag>
        </Tooltip>
    ) : null
}

export const NotebookExpandButton = (props: Pick<LemonButtonProps, 'size' | 'type'>): JSX.Element => {
    const { isExpanded } = useValues(notebookSettingsLogic)
    const { setIsExpanded } = useActions(notebookSettingsLogic)

    return (
        <LemonButton
            {...props}
            onClick={() => setIsExpanded(!isExpanded)}
            icon={<IconDocumentExpand mode={isExpanded ? 'expand' : 'collapse'} />}
            tooltip={isExpanded ? 'Fix content width' : 'Fill content width'}
            tooltipPlacement="left"
        />
    )
}

export const NotebookTableOfContentsButton = (props: Pick<LemonButtonProps, 'size' | 'type'>): JSX.Element => {
    const { showTableOfContents } = useValues(notebookSettingsLogic)
    const { setShowTableOfContents } = useActions(notebookSettingsLogic)

    return (
        <LemonButton
            {...props}
            onClick={() => setShowTableOfContents(!showTableOfContents)}
            icon={<IconBook />}
            tooltip={showTableOfContents ? 'Hide table of contents' : 'Show table of contents'}
            tooltipPlacement="left"
        />
    )
}
