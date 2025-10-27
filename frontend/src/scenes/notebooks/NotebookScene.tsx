import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconInfo, IconOpenSidebar } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

import { Notebook } from './Notebook/Notebook'
import { NotebookLoadingState } from './Notebook/NotebookLoadingState'
import { NotebookExpandButton, NotebookSyncInfo, NotebookTableOfContentsButton } from './Notebook/NotebookMeta'
import { NotebookShareModal } from './Notebook/NotebookShareModal'
import { notebookLogic } from './Notebook/notebookLogic'
import { NotebookMenu } from './NotebookMenu'
import { notebookPanelLogic } from './NotebookPanel/notebookPanelLogic'
import { LOCAL_NOTEBOOK_TEMPLATES } from './NotebookTemplates/notebookTemplates'
import { NotebookSceneLogicProps, notebookSceneLogic } from './notebookSceneLogic'
import { NotebookTarget } from './types'

interface NotebookSceneProps {
    shortId?: string
}

export const scene: SceneExport<NotebookSceneLogicProps> = {
    component: NotebookScene,
    logic: notebookSceneLogic,
    paramsToProps: ({ params: { shortId } }: { params: NotebookSceneProps }) => ({
        shortId: shortId || 'missing',
    }),
}

export function NotebookScene(): JSX.Element {
    const { notebookId, loading } = useValues(notebookSceneLogic)
    const { createNotebook } = useActions(notebookSceneLogic)
    const { notebook, conflictWarningVisible, accessDeniedToNotebook } = useValues(
        notebookLogic({ shortId: notebookId, target: NotebookTarget.Scene })
    )
    const { selectNotebook, closeSidePanel } = useActions(notebookPanelLogic)
    const { selectedNotebook, visibility } = useValues(notebookPanelLogic)

    useEffect(() => {
        if (notebookId === 'new') {
            // NOTE: We don't do this in the logic afterMount as the logic can get cached by the router
            createNotebook(NotebookTarget.Scene)
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [notebookId])

    useFileSystemLogView({
        type: 'notebook',
        ref: notebook?.short_id,
        enabled: Boolean(notebook?.short_id && notebookId !== 'new' && !loading && !conflictWarningVisible),
        deps: [notebook?.short_id, notebookId, loading, conflictWarningVisible],
    })

    if (accessDeniedToNotebook) {
        return <AccessDenied object="notebook" />
    }

    if (!notebook && !loading && !conflictWarningVisible) {
        return <NotFound object="notebook" />
    }

    if (visibility === 'visible' && selectedNotebook === notebookId) {
        return (
            <div className="flex flex-col justify-center items-center h-full text-secondary mx-10 flex-1">
                <h2 className="text-secondary">
                    This Notebook is open in the side panel <IconOpenSidebar />
                </h2>

                <p>
                    You can navigate around PostHog and <b>drag and drop</b> thing into it. Or you can close the sidebar
                    and it will be full screen here instead.
                </p>

                <LemonButton type="secondary" onClick={() => closeSidePanel()}>
                    Open it here instead
                </LemonButton>
            </div>
        )
    }

    const isTemplate = notebook?.is_template

    if (notebookId === 'new') {
        return <NotebookLoadingState />
    }

    return (
        <>
            <div className="flex items-center justify-between">
                <div className="flex gap-2 items-center">
                    <SceneBreadcrumbBackButton />
                    {isTemplate && <LemonTag type="highlight">TEMPLATE</LemonTag>}
                    <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
                </div>

                <div className="flex gap-2 items-center">
                    <NotebookSyncInfo shortId={notebookId} />

                    <NotebookMenu shortId={notebookId} />

                    <LemonButton
                        type="secondary"
                        icon={<IconInfo />}
                        size="small"
                        onClick={() => {
                            if (selectedNotebook === LOCAL_NOTEBOOK_TEMPLATES[0].short_id && visibility === 'visible') {
                                closeSidePanel()
                            } else {
                                selectNotebook(LOCAL_NOTEBOOK_TEMPLATES[0].short_id)
                            }
                        }}
                    >
                        {selectedNotebook === LOCAL_NOTEBOOK_TEMPLATES[0].short_id && visibility === 'visible'
                            ? 'Close '
                            : ''}
                        Guide
                    </LemonButton>
                    <NotebookTableOfContentsButton type="secondary" size="small" />
                    <NotebookExpandButton type="secondary" size="small" />
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => {
                            selectNotebook(notebookId)
                        }}
                        tooltip={
                            <>
                                Opens the notebook in a side panel, that can be accessed from anywhere in the PostHog
                                app. This is great for dragging and dropping elements like insights, recordings or even
                                feature flags into your active notebook.
                            </>
                        }
                        sideIcon={<IconOpenSidebar />}
                    >
                        Open in side panel
                    </LemonButton>
                </div>
            </div>

            <Notebook key={notebookId} shortId={notebookId} editable={!isTemplate} />
            <NotebookShareModal shortId={notebookId} />
        </>
    )
}
