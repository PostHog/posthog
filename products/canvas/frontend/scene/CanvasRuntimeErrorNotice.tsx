import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasErrorType } from '../canvasAnalytics'
import { canvasHistoryLogic } from '../history/canvasHistoryLogic'
import { canvasSidePanelLogic } from '../sidePanel/canvasSidePanelLogic'
import { canvasChatLogic } from '../sidePanel/chat/canvasChatLogic'
import { canvasSceneLogic } from './canvasSceneLogic'

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
        <div className="flex items-center gap-1" data-attr="canvas-runtime-error">
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex items-center gap-1" />}>
                    <IconWarning className="text-destructive-foreground" />
                    <Text size="xs" variant="destructive">
                        Runtime error
                    </Text>
                </TooltipTrigger>
                <TooltipContent>
                    <span className="block max-w-sm whitespace-pre-wrap break-words">{runtimeError}</span>
                </TooltipContent>
            </Tooltip>
            <Button
                size="xs"
                variant="outline"
                loading={fixRequestPending}
                onClick={askAgentToFix}
                data-attr="canvas-runtime-error-ask-fix"
            >
                Ask agent to fix
            </Button>
        </div>
    )
}
