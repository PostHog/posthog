import './NotebookPanel.scss'

import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExpand45 } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { SidePanelContentContainer } from '~/layout/navigation-3000/sidepanel/SidePanelContentContainer'
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
        <div ref={ref} className={cn('NotebookPanel', 'bg-transparent')} {...dropProperties}>
            {!droppedResource ? (
                <>
                    <SidePanelContentContainer>
                        <SidePanelPaneHeader title="Notebooks">
                            <div className="flex gap-1 overflow-hidden">
                                <NotebookListMini
                                    selectedNotebookId={selectedNotebook}
                                    onSelectNotebook={(notebook) => {
                                        selectNotebook(notebook.short_id)
                                    }}
                                    buttonProps={{ className: 'max-w-[120px]', truncate: true }}
                                />

                                {selectedNotebook && <NotebookSyncInfo shortId={selectedNotebook} />}
                            </div>

                            <div className="flex-1" />
                            <div className="flex items-center gap-1">
                                <NotebookMenu shortId={selectedNotebook} />
                                {contentWidthHasEffect && <NotebookExpandButton size="small" inPanel={true} />}
                                <Link
                                    buttonProps={{
                                        iconOnly: true,
                                    }}
                                    to={urls.notebook(selectedNotebook)}
                                    onClick={() => closeSidePanel()}
                                    target="_blank"
                                    tooltip="Open as main focus"
                                    tooltipPlacement="bottom-end"
                                >
                                    <IconExpand45 className="text-tertiary size-3 group-hover:text-primary z-10" />
                                </Link>
                            </div>
                        </SidePanelPaneHeader>
                        <Notebook
                            key={selectedNotebook}
                            shortId={selectedNotebook}
                            editable={editable}
                            initialAutofocus={initialAutofocus}
                        />
                    </SidePanelContentContainer>
                </>
            ) : null}

            <NotebookPanelDropzone />
        </div>
    )
}
