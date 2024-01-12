import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { sidePanelCanvasLogic } from './sidePanelCanvasLogic'

export const SidePanelCanvas = (): JSX.Element | null => {
    const { canvas, canvasId, title } = useValues(sidePanelCanvasLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    useKeyboardHotkeys(
        {
            escape: {
                action: function () {
                    closeSidePanel()
                },
            },
        },
        []
    )

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title={title}>
                <NotebookSelectButton
                    size="small"
                    onNotebookOpened={(theNotebookLogic) => {
                        theNotebookLogic.actions.insertAfterLastNode(canvas)
                    }}
                >
                    Save as Notebook
                </NotebookSelectButton>
            </SidePanelPaneHeader>
            <div className="p-3">
                <Notebook
                    key={canvasId}
                    editable={false}
                    shortId={`canvas-${canvasId}`}
                    mode="canvas"
                    initialContent={{
                        type: 'doc',
                        content: canvas ?? [],
                    }}
                />
            </div>
        </div>
    )
}
