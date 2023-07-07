import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { notebookLogic } from './Notebook/notebookLogic'
import { Notebook } from './Notebook/Notebook'
import { NotFound } from 'lib/components/NotFound'
import { NotebookSceneLogicProps, notebookSceneLogic } from './notebookSceneLogic'
import { NotebookMode } from '~/types'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { notebookSidebarLogic } from './Notebook/notebookSidebarLogic'
import { NotebookExpandButton, NotebookSyncInfo } from './Notebook/NotebookMeta'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { IconArrowRight, IconDelete, IconEllipsis, IconExport, IconHelpOutline } from 'lib/lemon-ui/icons'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { notebooksListLogic } from './Notebook/notebooksListLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LOCAL_NOTEBOOK_TEMPLATES } from './NotebookTemplates/notebookTemplates'

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
    const { notebook, notebookLoading, conflictWarningVisible } = useValues(notebookLogic({ shortId: notebookId }))
    const { exportJSON } = useActions(notebookLogic({ shortId: notebookId }))
    const { selectNotebook, setNotebookSideBarShown } = useActions(notebookSidebarLogic)
    const { selectedNotebook, notebookSideBarShown } = useValues(notebookSidebarLogic)

    if (!notebook && !notebookLoading && !conflictWarningVisible) {
        return <NotFound object="notebook" />
    }

    if (notebookSideBarShown && selectedNotebook === notebookId) {
        return (
            <div className="flex flex-col justify-center items-center h-full text-muted-alt mx-10">
                <h2 className="text-muted-alt">
                    This Notebook is open in the sidebar <IconArrowRight />
                </h2>

                <p>
                    You can navigate around PostHog and <b>drag and drop</b> thing into it. Or you can close the sidebar
                    and it will be full screen here instead.
                </p>

                <LemonButton type="secondary" onClick={() => setNotebookSideBarShown(false)}>
                    Open it here instead
                </LemonButton>
            </div>
        )
    }

    const editEnabled = !notebook?.is_template

    return (
        <div className="NotebookScene">
            <div className="flex items-center justify-between border-b py-2 mb-2 sticky top-0 bg-bg-light z-10">
                <div className="flex gap-2 items-center">
                    {notebook?.is_template && <LemonTag type="highlight">TEMPLATE</LemonTag>}
                    <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
                </div>

                <div className="flex gap-2 items-center">
                    <NotebookSyncInfo shortId={notebookId} />

                    <LemonMenu
                        items={[
                            {
                                items: [
                                    {
                                        label: 'Export JSON',
                                        icon: <IconExport />,
                                        onClick: () => {
                                            exportJSON()
                                        },
                                    },
                                    editEnabled && {
                                        label: 'Delete',
                                        icon: <IconDelete />,
                                        status: 'danger',

                                        onClick: () => {
                                            notebooksListLogic.actions.deleteNotebook(notebookId, notebook?.title)
                                            router.actions.push(urls.notebooks())
                                        },
                                    },
                                ],
                            },
                        ]}
                        actionable
                    >
                        <LemonButton aria-label="more" icon={<IconEllipsis />} status="stealth" size="small" />
                    </LemonMenu>
                    <LemonButton
                        type="secondary"
                        icon={<IconHelpOutline />}
                        onClick={() => {
                            selectNotebook(LOCAL_NOTEBOOK_TEMPLATES[0].short_id)
                            setNotebookSideBarShown(true)
                        }}
                    >
                        Guide
                    </LemonButton>
                    <NotebookExpandButton type="secondary" />
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            selectNotebook(notebookId)
                            setNotebookSideBarShown(true)
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

                    {!editEnabled ? null : mode === NotebookMode.Edit ? (
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

            <Notebook key={notebookId} shortId={notebookId} editable={editEnabled && mode === NotebookMode.Edit} />
        </div>
    )
}
