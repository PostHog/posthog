import { IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'

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
            <header className="flex items-center justify-between gap-2 font-semibold shrink-0 p-1 border-b">
                <span className="pl-2 font-semibold flex-1">{title}</span>
                <LemonButton size="small" icon={<IconNotebook />}>
                    Save as Notebook
                </LemonButton>
                <LemonButton size="small" onClick={() => closeSidePanel()}>
                    Done
                </LemonButton>
            </header>
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
