import { BindLogic } from 'kea'

import { CanvasChatBody } from './CanvasChatBody'
import { CanvasChatComposer } from './CanvasChatComposer'
import { canvasChatLogic } from './canvasChatLogic'
import { CanvasChatStatus } from './CanvasChatStatus'

/** The Chat tab: the viewer's run on this canvas and the composer that continues it. */
export function CanvasChatTab({ canvasId }: { canvasId: string }): JSX.Element {
    return (
        <BindLogic logic={canvasChatLogic} props={{ id: canvasId }}>
            <div className="flex h-full min-h-0 flex-col" data-attr="canvas-chat-tab">
                <CanvasChatStatus />
                <div className="min-h-0 flex-1">
                    <CanvasChatBody />
                </div>
                <CanvasChatComposer />
            </div>
        </BindLogic>
    )
}
