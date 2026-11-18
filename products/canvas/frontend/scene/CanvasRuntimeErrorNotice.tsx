import { useValues } from 'kea'

import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasStatusIssue } from './CanvasStatusIssue'

/** The error the rendered canvas threw. The web app only views canvases, so the fix goes through the person's agent. */
export function CanvasRuntimeErrorNotice(): JSX.Element | null {
    const { runtimeError, canvas } = useValues(canvasSceneLogic)

    if (!runtimeError || !canvas) {
        return null
    }
    return (
        <div className="flex items-center" data-attr="canvas-runtime-error">
            <CanvasStatusIssue
                label="Runtime error"
                title="The canvas threw an error"
                description="Parts of the canvas may not work. Ask your agent to fix it with the PostHog MCP server."
                details={[runtimeError]}
                dataAttr="canvas-runtime-error-details"
            />
        </div>
    )
}
