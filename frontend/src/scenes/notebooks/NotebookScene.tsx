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
import { NotebookMeta } from './Notebook/NotebookMeta'

interface NotebookSceneProps {
    id?: string
}

export const scene: SceneExport = {
    component: NotebookScene,
    logic: notebookSceneLogic,
    paramsToProps: ({ params: { id } }: { params: NotebookSceneProps }): NotebookSceneLogicProps => ({
        id: id || 'missing',
    }),
}

export function NotebookScene(): JSX.Element {
    const { notebookId, mode } = useValues(notebookSceneLogic)
    const { setNotebookMode } = useActions(notebookSceneLogic)
    const { notebook, notebookLoading } = useValues(notebookLogic({ id: notebookId }))
    const { selectNotebook, setNotebookSideBarShown } = useActions(notebookSidebarLogic)

    if (!notebook && !notebookLoading) {
        return <NotFound object="notebook" />
    }

    return (
        <div className="NotebookScene mt-4">
            <div className="flex items-center justify-between">
                <NotebookMeta id={notebookId} />
                <div className="flex gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            selectNotebook(notebookId)
                            setNotebookSideBarShown(true)
                            router.actions.push(urls.notebooks())
                        }}
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

            <Notebook id={notebookId} editable={mode === NotebookMode.Edit} />
        </div>
    )
}
