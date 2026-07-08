import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { AgentBadgeRotator } from './AgentBadgeRotator'
import { mcpHintLogic } from './mcpHintLogic'
import { MCPInstallCommand } from './MCPInstallCommand'
import { type SurfaceKey, formatDerivedToastPrompt, getSurfacePrompts } from './prompts'

export function MCPHintToast({
    surfaceKey,
    derivedPrompt,
}: {
    surfaceKey: SurfaceKey
    /** If provided, replaces the per-surface default toast prompt with this action-derived string. */
    derivedPrompt?: string
}): JSX.Element {
    const { userRole } = useValues(mcpHintLogic)
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
            <MCPInstallCommand size="sm" silentCopy />
        </div>
    )
}
