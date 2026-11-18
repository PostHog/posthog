import { useActions } from 'kea'
import { useMemo } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { uuid } from 'lib/utils/dom'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { loadNotebookFromJSON } from './loadNotebookFromJSON'
import { Notebook } from './Notebook/Notebook'
import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'
import { QuillNotebookCanvasActions } from './QuillNotebookCanvasActions'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <SceneContent className="h-full">
            <SceneTitleSection
                name="Canvas"
                resourceType={{
                    type: 'notebook',
                }}
                forceBackTo={{
                    path: urls.notebooks(),
                    name: 'Notebooks',
                    key: 'notebooks',
                }}
                actions={
                    todayRailNav ? (
                        <QuillNotebookCanvasActions logicProps={logicProps} />
                    ) : (
                        <>
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Clear canvas',
                                        onClick: () => setLocalContent({ type: 'doc', content: [] }),
                                    },
                                    {
                                        label: 'Export as JSON',
                                        onClick: () => exportJSON(),
                                    },
                                    {
                                        label: 'Load from JSON',
                                        onClick: () => loadNotebookFromJSON(setLocalContent),
                                    },
                                ]}
                            >
                                <LemonButton icon={<IconEllipsis />} size="small" />
                            </LemonMenu>
                            <LemonButton
                                type="secondary"
                                onClick={() => {
                                    void copyToClipboard(window.location.href, 'Canvas URL')
                                }}
                                size="small"
                            >
                                Share
                            </LemonButton>
                            <LemonButton type="primary" onClick={duplicateNotebook} size="small">
                                Save as Notebook
                            </LemonButton>
                        </>
                    )
                }
            />
            <div className="relative flex-1">
                <Notebook {...logicProps} />
            </div>
        </SceneContent>
    )
}
