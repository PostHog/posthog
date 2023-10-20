import { SceneExport } from 'scenes/sceneTypes'
import { NotebookLogicProps } from './Notebook/notebookLogic'
import { Notebook } from './Notebook/Notebook'
import './NotebookScene.scss'
import { useMemo } from 'react'
import { uuid } from 'lib/utils'

// interface NotebookCanvasProps {
//     initialState?: string | JSONContent
//     syncWithUrl?: boolean
// }

export const scene: SceneExport = {
    component: NotebookCanvas,
    // paramsToProps: ({ params: { state } }: { params: NotebookCanvasSceneProps }): NotebookCanvasSceneLogicProps => ({
    //     state: state,
    // }),
}

export function NotebookCanvas(): JSX.Element {
    const id = useMemo(() => uuid(), [])

    const logicProps: NotebookLogicProps = {
        shortId: `canvas-${id}`,
        mode: 'canvas',
    }

    return (
        <div className="absolute inset-0 p-2">
            <Notebook {...logicProps} />
        </div>
    )
}
