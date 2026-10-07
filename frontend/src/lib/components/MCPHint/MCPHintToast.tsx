import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { AgentBadgeRotator } from './AgentBadgeRotator'
import { MCPHintActions } from './MCPHintActions'
import { mcpHintLogic } from './mcpHintLogic'
import { type SurfaceKey, formatDerivedToastPrompt, getSurfacePrompts } from './prompts'

export function MCPHintToast({
    surfaceKey,
    derivedPrompt,
    toastId,
}: {
    surfaceKey: SurfaceKey
    /** If provided, replaces the per-surface default toast prompt with this action-derived string. */
    derivedPrompt?: string
    toastId?: string
}): JSX.Element {
    const { userRole } = useValues(mcpHintLogic)
    const { keepHintOpen } = useActions(mcpHintLogic)
    const prompt = derivedPrompt
        ? formatDerivedToastPrompt(derivedPrompt)
        : getSurfacePrompts(surfaceKey, { role: userRole }).toast

    return (
        <div className="flex flex-col gap-1 py-1 pr-1 text-default min-w-0 items-start">
            <div className="flex items-center gap-1.5 text-sm">
                <IconSparkles className="size-4 shrink-0" />
                <span>
                    Next time, ask <AgentBadgeRotator /> to do it for you:
                </span>
            </div>
            <div className="text-xs italic text-muted leading-snug">{prompt}</div>
            <MCPHintActions
                surfaceKey={surfaceKey}
                example={prompt}
                placement="toast"
                onMenuOpen={toastId ? () => keepHintOpen(toastId) : undefined}
            />
        </div>
    )
}
