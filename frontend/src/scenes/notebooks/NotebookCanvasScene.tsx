import './NotebookScene.scss'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { uuid } from 'lib/utils'
import { useMemo } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { Notebook } from './Notebook/Notebook'
import { notebookLogic, NotebookLogicProps } from './Notebook/notebookLogic'

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

    const is3000 = useFeatureFlag('POSTHOG_3000', 'test')

    if (!is3000) {
        return <NotFound object="canvas" caption={<>Canvas mode requires PostHog 3000</>} />
    }

    // TODO: The absolute positioning doesn't work so well in non-3000 mode

    return (
        <>
            <PageHeader
                title="Canvas"
                buttons={
                    <>
                        <LemonButton type="primary" onClick={duplicateNotebook}>
                            Save as Notebook
                        </LemonButton>
                    </>
                }
            />
            <div className="flex flex-col flex-1">
                <div className="relative flex-1">
                    <div className="absolute inset-0 p-3 flex flex-col overflow-y-auto">
                        <LemonBanner type="info" className="mb-4">
                            <b>This is a canvas.</b> You can change anything you like and it is persisted to the URL for
                            easy sharing.
                        </LemonBanner>
                        <Notebook {...logicProps} />
                    </div>
                </div>
            </div>
        </>
    )
}
