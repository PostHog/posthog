import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconOpenSidebar } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'

import { Notebook } from './Notebook/Notebook'
import { NotebookLoadingState } from './Notebook/NotebookLoadingState'
import { notebookLogic } from './Notebook/notebookLogic'
import {
    NotebookExpandButton,
    NotebookKernelInfoButton,
    NotebookPresence,
    NotebookSyncInfo,
} from './Notebook/NotebookMeta'
import { NotebookShareModal } from './Notebook/NotebookShareModal'
import { NotebookMenu } from './NotebookMenu'
import { notebookPanelLogic } from './NotebookPanel/notebookPanelLogic'
import { NotebookSceneLogicProps, notebookSceneLogic } from './notebookSceneLogic'
import { NotebookSceneMenuBar } from './NotebookSceneMenuBar'
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
    const { notebook, accessDeniedToNotebook } = useValues(
        notebookLogic({ shortId: notebookId, target: NotebookTarget.Scene })
    )
    const { selectNotebook, closeSidePanel } = useActions(notebookPanelLogic)
    const { selectedNotebook, visibility } = useValues(notebookPanelLogic)
    const [isMarkdownSourceOpen, setIsMarkdownSourceOpen] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    useEffect(() => {
        if (notebookId === 'new') {
            // NOTE: We don't do this in the logic afterMount as the logic can get cached by the router
            let content: JSONContent[] | undefined
            let title: string | undefined

            const searchParams = new URLSearchParams(router.values.location.search)
            const contentParam = searchParams.get('notebook')
            if (contentParam) {
                try {
                    const decoded = decodeURIComponent(contentParam)
                    const parsedNotebook = JSON.parse(decoded)
                    content = parsedNotebook['body'] as JSONContent[]
                    title = parsedNotebook['title'] as string
                } catch (error) {
                    console.error('Failed to parse content query parameter:', error)
                }
            }

            createNotebook(NotebookTarget.Scene, title, content)
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [notebookId])

    useEffect(() => {
        setIsMarkdownSourceOpen(false)
    }, [notebookId])

    useFileSystemLogView({
        type: 'notebook',
        ref: notebook?.short_id,
        enabled: Boolean(notebook?.short_id && notebookId !== 'new' && !loading),
    })

    if (accessDeniedToNotebook) {
        return <AccessDenied object="notebook" />
    }

    if (!notebook && !loading) {
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
            <NotebookSceneMenuBar shortId={notebookId} />
            <div className={cn('flex items-center justify-between', sceneMenuBarEnabled && 'mt-2')}>
                <div className="flex gap-2 items-center">
                    <SceneBreadcrumbBackButton />
                    {isTemplate && <LemonTag type="highlight">TEMPLATE</LemonTag>}
                    <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
                </div>

                <div className="flex gap-2 items-center">
                    <NotebookSyncInfo shortId={notebookId} />
                    <NotebookPresence shortId={notebookId} />

                    {!sceneMenuBarEnabled && <NotebookMenu shortId={notebookId} />}

                    {!sceneMenuBarEnabled && (
                        <BindLogic logic={notebookLogic} props={{ shortId: notebookId, target: NotebookTarget.Scene }}>
                            <NotebookKernelInfoButton
                                type="secondary"
                                size="small"
                                onBeforeShowKernelInfo={() => setIsMarkdownSourceOpen(false)}
                            />
                        </BindLogic>
                    )}
                    {!sceneMenuBarEnabled && <NotebookExpandButton type="secondary" size="small" inPanel={false} />}
                    {!sceneMenuBarEnabled && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => {
                                selectNotebook(notebookId)
                            }}
                            tooltip={
                                <>
                                    Opens the notebook in a context panel, that can be accessed from anywhere in the
                                    PostHog app. This is great for dragging and dropping elements like insights,
                                    recordings or even feature flags into your active notebook.
                                </>
                            }
                            aria-label="Open in context panel"
                            sideIcon={<IconOpenSidebar />}
                        >
                            <span className="hidden lg:inline">Open in context panel</span>
                        </LemonButton>
                    )}
                </div>
            </div>

            <Notebook
                key={notebookId}
                shortId={notebookId}
                editable={!isTemplate}
                markdownSourceOpen={isMarkdownSourceOpen}
                onMarkdownSourceOpenChange={setIsMarkdownSourceOpen}
            />
            <NotebookShareModal shortId={notebookId} />
        </>
    )
}
