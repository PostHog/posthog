import { SceneExport } from 'scenes/sceneTypes'
import { NotebookLogicProps } from './Notebook/notebookLogic'
import { Notebook } from './Notebook/Notebook'
import './NotebookScene.scss'
import { useMemo } from 'react'
import { uuid } from 'lib/utils'

export const scene: SceneExport = {
    component: NotebookCanvas,
}

export function NotebookCanvas(): JSX.Element {
    const id = useMemo(() => uuid(), [])

    const logicProps: NotebookLogicProps = {
        shortId: `canvas-${id}`,
        mode: 'canvas',
    }

    return (
        <div className="absolute inset-0 p-3">
            <Notebook {...logicProps} />
        </div>
    )
}
