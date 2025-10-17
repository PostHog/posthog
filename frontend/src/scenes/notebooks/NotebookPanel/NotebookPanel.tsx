import './NotebookPanel.scss'

import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { urls } from 'scenes/urls'

import { SidePanelPaneHeader } from '~/layout/navigation-3000/sidepanel/components/SidePanelPaneHeader'

import { Notebook } from '../Notebook/Notebook'
import { NotebookListMini } from '../Notebook/NotebookListMini'
import { NotebookExpandButton, NotebookSyncInfo } from '../Notebook/NotebookMeta'
import { notebookLogic } from '../Notebook/notebookLogic'
import { NotebookMenu } from '../NotebookMenu'
import { NotebookTarget } from '../types'
import { NotebookPanelDropzone } from './NotebookPanelDropzone'
import { notebookPanelLogic } from './notebookPanelLogic'

export function NotebookPanel(): JSX.Element | null {
    const { selectedNotebook, initialAutofocus, droppedResource, dropProperties } = useValues(notebookPanelLogic)
    const { selectNotebook, closeSidePanel } = useActions(notebookPanelLogic)
    const { notebook } = useValues(notebookLogic({ shortId: selectedNotebook, target: NotebookTarget.Popover }))
    const editable = !notebook?.is_template

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        832: 'medium',
    })

    const contentWidthHasEffect = useMemo(() => size === 'medium', [size])

    return (
        <div ref={ref} className="NotebookPanel" {...dropProperties}>
            {!droppedResource ? (
                <>
                    <SidePanelPaneHeader>
                        <NotebookListMini
                            selectedNotebookId={selectedNotebook}
                            onSelectNotebook={(notebook) => {
                                selectNotebook(notebook.short_id)
                            }}
                        />
                        {selectedNotebook && <NotebookSyncInfo shortId={selectedNotebook} />}

                        <div className="flex-1" />

                        <NotebookMenu shortId={selectedNotebook} />
                        {contentWidthHasEffect && <NotebookExpandButton size="small" />}
                        <LemonButton
                            size="small"
                            to={urls.notebook(selectedNotebook)}
                            onClick={() => closeSidePanel()}
                            icon={<IconExternal />}
                            targetBlank
                            tooltip="Open as main focus"
                            tooltipPlacement="bottom-end"
                        />
                    </SidePanelPaneHeader>

                    <div className="flex flex-col flex-1 overflow-y-auto p-3 bg-[var(--color-bg-surface-primary)]">
                        <Notebook
                            key={selectedNotebook}
                            shortId={selectedNotebook}
                            editable={editable}
                            initialAutofocus={initialAutofocus}
                        />
                    </div>
                </>
            ) : null}

            <NotebookPanelDropzone />
        </div>
    )
}
