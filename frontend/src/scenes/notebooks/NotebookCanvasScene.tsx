import { SceneExport } from 'scenes/sceneTypes'
import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'
import { Notebook } from './Notebook/Notebook'
import './NotebookScene.scss'
import { useMemo } from 'react'
import { uuid } from 'lib/utils'
import { useActions } from 'kea'
import { LemonBanner } from '@posthog/lemon-ui'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { NotFound } from 'lib/components/NotFound'

export const scene: SceneExport = {
    component: NotebookCanvas,
}

export function NotebookCanvas(): JSX.Element {
    const id = useMemo(() => uuid(), [])

    const logicProps: NotebookLogicProps = {
        shortId: `canvas-${id}`,
        mode: 'canvas',
    }

    const { duplicateNotebook } = useActions(notebookLogic(logicProps))

    const is3000 = useFeatureFlag('POSTHOG_3000')

    if (!is3000) {
        return <NotFound object="canvas" caption={<>Canvas mode requires PostHog 3000</>} />
    }

    // TODO: The absolute positioning doesn't work so well in non-3000 mode

    return (
        <div className="flex flex-col flex-1">
            <LemonBanner
                type="info"
                action={{
                    onClick: duplicateNotebook,
                    children: 'Save as Notebook',
                }}
                className="mx-2 mt-2"
            >
                <b>This is a canvas.</b> You can change anything you like and it is persisted to the URL for easy
                sharing.
            </LemonBanner>
            <div className="relative flex-1">
                <div className="absolute inset-0 p-3 flex flex-column overflow-y-auto">
                    <Notebook {...logicProps} />
                </div>
            </div>
        </div>
    )
}
