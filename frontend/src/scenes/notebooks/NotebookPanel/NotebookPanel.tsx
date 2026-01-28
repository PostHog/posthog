import './NotebookPanel.scss'

import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconExpand45 } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')
    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        832: 'medium',
    })

    const contentWidthHasEffect = useMemo(() => size === 'medium', [size])

    return (
        <div
            ref={ref}
            className={cn('NotebookPanel', {
                'rounded-l-lg bg-transparent': isRemovingSidePanelFlag,
            })}
            {...dropProperties}
        >
            {!droppedResource ? (
                <>
                    <SidePanelPaneHeader>
                        <div className="flex gap-1">
                            <NotebookListMini
                                selectedNotebookId={selectedNotebook}
                                onSelectNotebook={(notebook) => {
                                    selectNotebook(notebook.short_id)
                                }}
                            />

                            {selectedNotebook && <NotebookSyncInfo shortId={selectedNotebook} />}
                        </div>

                        <div className="flex-1" />
                        <div
                            className={cn('flex items-center', {
                                'flex items-center gap-1': isRemovingSidePanelFlag,
                            })}
                        >
                            {isRemovingSidePanelFlag && selectedNotebook && notebook && (
                                <UserActivityIndicator at={notebook.last_modified_at} by={notebook.last_modified_by} />
                            )}

                            <NotebookMenu shortId={selectedNotebook} />
                            {contentWidthHasEffect && <NotebookExpandButton size="small" />}
                            {isRemovingSidePanelFlag ? (
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
                            ) : (
                                <LemonButton
                                    size="small"
                                    sideIcon={<IconExpand45 />}
                                    to={urls.notebook(selectedNotebook)}
                                    onClick={() => closeSidePanel()}
                                    targetBlank
                                    tooltip="Open as main focus"
                                    tooltipPlacement="bottom-end"
                                />
                            )}
                        </div>
                    </SidePanelPaneHeader>

                    <SidePanelContentContainer flagOffClassName="flex flex-col flex-1 overflow-y-auto p-3 bg-[var(--color-bg-surface-primary)]">
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
