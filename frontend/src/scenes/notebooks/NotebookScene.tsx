import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { notebookLogic } from './Notebook/notebookLogic'
import { Notebook } from './Notebook/Notebook'
import { NotFound } from 'lib/components/NotFound'
import { NotebookSceneLogicProps, notebookSceneLogic } from './notebookSceneLogic'
import { NotebookMode } from '~/types'

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
    const { notebook, notebookLoading } = useValues(notebookLogic({ id: notebookId }))

    if (!notebook && !notebookLoading) {
        return <NotFound object="notebook" />
    }

    return (
        <div className="NotebookScene mt-4">
            <Notebook id={notebookId} editable={mode === NotebookMode.Edit} />
        </div>
    )
}
