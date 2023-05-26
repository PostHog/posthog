import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { notebookLogic } from './Notebook/notebookLogic'
import { Notebook } from './Notebook/Notebook'
import { NotFound } from 'lib/components/NotFound'
import { NotebookSceneLogicProps, notebookSceneLogic } from './notebookSceneLogic'
import { NotebookMode } from '~/types'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { notebookSidebarLogic } from './Notebook/notebookSidebarLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { NotebookExpandButton, NotebookSyncInfo } from './Notebook/NotebookMeta'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'

interface NotebookSceneProps {
    shortId?: string
}

export const scene: SceneExport = {
    component: NotebookScene,
    logic: notebookSceneLogic,
    paramsToProps: ({ params: { shortId } }: { params: NotebookSceneProps }): NotebookSceneLogicProps => ({
        shortId: shortId || 'missing',
    }),
}

export function NotebookScene(): JSX.Element {
    const { notebookId, mode } = useValues(notebookSceneLogic)
    const { setNotebookMode } = useActions(notebookSceneLogic)
    const { notebook, notebookLoading } = useValues(notebookLogic({ shortId: notebookId }))
    const { selectNotebook, setNotebookSideBarShown } = useActions(notebookSidebarLogic)

    if (!notebook && !notebookLoading) {
        return <NotFound object="notebook" />
    }

    return (
        <div className="NotebookScene mt-4">
            <div className="flex items-center justify-between">
                <div className="flex gap-2 items-center">
                    <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
                </div>

                <div className="flex gap-2 items-center">
                    <NotebookSyncInfo shortId={notebookId} />

                    <NotebookExpandButton status="primary-alt" size="small" noPadding />

                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            selectNotebook(notebookId)
                            setNotebookSideBarShown(true)
                            router.actions.push(urls.notebooks())
                        }}
                        tooltip={
                            <>
                                Pins the notebook to the right, allowing you to view it while navigating the rest of
                                PostHog. This is great for dragging and dropping elements like Insights, Recordings or
                                even Feature Flags into your active Notebook.
                            </>
                        }
                    >
                        Pin to side
                    </LemonButton>

                    {mode === NotebookMode.Edit ? (
                        <>
                            <LemonButton type="primary" onClick={() => setNotebookMode(NotebookMode.View)}>
                                Done
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            <LemonButton type="primary" onClick={() => setNotebookMode(NotebookMode.Edit)}>
                                Edit
                            </LemonButton>
                        </>
                    )}
                </div>
            </div>

            <LemonDivider />

            <Notebook key={notebookId} shortId={notebookId} editable={mode === NotebookMode.Edit} />
        </div>
    )
}
