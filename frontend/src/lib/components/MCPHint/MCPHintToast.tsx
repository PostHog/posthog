import { IconSparkles } from '@posthog/icons'

import { AgentBadgeRotator } from './AgentBadgeRotator'
import { MCPInstallCommand } from './MCPInstallCommand'
import { SURFACE_PROMPTS, type SurfaceKey, type SurfacePromptContext } from './prompts'

export function MCPHintToast({
    surfaceKey,
    context,
}: {
    surfaceKey: SurfaceKey
    context?: SurfacePromptContext
}): JSX.Element {
    const prompt = SURFACE_PROMPTS[surfaceKey].toast(context)

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
