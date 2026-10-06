import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { canvasErrorType } from '../canvasAnalytics'
import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
import { canvasSidePanelLogic } from '../sidePanel/canvasSidePanelLogic'
import { canvasChatLogic } from '../sidePanel/chat/canvasChatLogic'
import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasStatusIssue } from './CanvasStatusIssue'

/**
 * The error the rendered canvas threw, with a way to hand it to the agent. A live build goes
 * to the canvas's authoring agent as a fix request. Unbuilt source has no build to name, so the
 * error goes into the chat composer instead.
 */
export function CanvasRuntimeErrorNotice(): JSX.Element | null {
    const { runtimeError, liveBuild, canvas, fixRequestPending } = useValues(canvasSceneLogic)
    const { requestFix } = useActions(canvasSceneLogic)
    const { browseVersionId } = useValues(canvasHistoryLogic)
    const { openTab } = useActions(canvasSidePanelLogic)
    const { setDraft } = useActions(canvasChatLogic({ id: canvas?.id ?? '' }))

    if (!runtimeError || !canvas) {
        return null
    }
    const buildId = !browseVersionId ? (liveBuild?.id ?? null) : null
    const askAgentToFix = (): void => {
        if (buildId) {
            requestFix({ buildId, errorType: canvasErrorType(runtimeError) })
            return
        }
        setDraft(`The canvas threw a runtime error: "${runtimeError}". Fix it.`)
        openTab('chat', canvas.id)
    }

    return (
        <div className="flex items-center" data-attr="canvas-runtime-error">
            <CanvasStatusIssue
                label="Runtime error"
                title="The canvas threw an error"
                description={
                    buildId
                        ? 'Parts of the canvas may not work. Ask the agent that wrote it to fix the error.'
                        : 'Parts of the canvas may not work. Ask the agent to fix it from the chat.'
                }
                details={[runtimeError]}
                dataAttr="canvas-runtime-error-details"
                actions={
                    <Button
                        size="sm"
                        variant="primary"
                        loading={fixRequestPending}
                        onClick={askAgentToFix}
                        data-attr="canvas-runtime-error-ask-fix"
                    >
                        Ask agent to fix
                    </Button>
                }
            />
        </div>
    )
}
