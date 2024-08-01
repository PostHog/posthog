import './NotebookScene.scss'

import { IconEllipsis } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu, lemonToast } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { uuid } from 'lib/utils'
import { getTextFromFile, selectFiles } from 'lib/utils/file-utils'
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

    const { duplicateNotebook, exportJSON, setLocalContent } = useActions(notebookLogic(logicProps))

    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <LemonMenu
                            items={[
                                {
                                    label: 'Clear canvas',
                                    onClick: () => setLocalContent({ type: 'doc', content: [] }, true),
                                },
                                {
                                    label: 'Export as JSON',
                                    onClick: () => exportJSON(),
                                },
                                {
                                    label: 'Load from JSON',
                                    onClick: () => {
                                        void selectFiles({
                                            contentType: 'application/json',
                                            multiple: false,
                                        })
                                            .then((files) => getTextFromFile(files[0]))
                                            .then((text) => {
                                                const data = JSON.parse(text)
                                                if (data.type !== 'doc') {
                                                    throw new Error('Not a notebook')
                                                }
                                                // Looks like a notebook
                                                setLocalContent(data, true)
                                            })
                                            .catch((e) => {
                                                lemonToast.error(e.message)
                                            })
                                    },
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} size="small" />
                        </LemonMenu>
                        <LemonButton type="primary" onClick={duplicateNotebook}>
                            Save as Notebook
                        </LemonButton>
                    </>
                }
            />
            <div className="flex flex-col flex-1">
                <div className="relative flex-1">
                    <div className="absolute inset-0 flex flex-col overflow-y-auto">
                        <LemonBanner type="info" className="mb-4" dismissKey="canvas-intro">
                            <b>This is a canvas.</b> It's a Notebook that is only saved in the URL so you can share it
                            with others. It's not saved to your account.
                        </LemonBanner>
                        <Notebook {...logicProps} />
                    </div>
                </div>
            </div>
        </>
    )
}
