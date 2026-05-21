import { useActions } from 'kea'
import { useState } from 'react'

import { IconHide, IconSparkles } from '@posthog/icons'
import { LemonButton, Popover, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { AgentBadgeRotator } from './AgentBadgeRotator'
import { mcpHintLogic } from './mcpHintLogic'
import { MCPInstallCommand } from './MCPInstallCommand'
import { SURFACE_PROMPTS, type SurfaceKey, type SurfacePromptContext } from './prompts'

export function MCPHintToast({
    surfaceKey,
    context,
}: {
    surfaceKey: SurfaceKey
    context?: SurfacePromptContext
}): JSX.Element {
    const { dismissSurface, dismissAll } = useActions(mcpHintLogic)
    const [hidePopoverOpen, setHidePopoverOpen] = useState(false)

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
            <div className="mt-1 flex items-center gap-2 self-stretch justify-between">
                <MCPInstallCommand size="sm" silentCopy />
                <Popover
                    visible={hidePopoverOpen}
                    onClickOutside={() => setHidePopoverOpen(false)}
                    placement="top-end"
                    overlay={
                        <div className="flex flex-col gap-0.5 p-1 min-w-48">
                            <Tooltip title="Stop suggesting MCP for this kind of action. You'll still see hints for other actions, at most once a week.">
                                <LemonButton
                                    size="small"
                                    fullWidth
                                    onClick={() => {
                                        setHidePopoverOpen(false)
                                        dismissSurface(surfaceKey)
                                    }}
                                    data-attr="mcp-hint-hide-surface"
                                >
                                    Hide this hint
                                </LemonButton>
                            </Tooltip>
                            <Tooltip title="Turn off MCP hints everywhere. If you keep them on, you'll only see one at most per week.">
                                <LemonButton
                                    size="small"
                                    status="danger"
                                    fullWidth
                                    onClick={() => {
                                        setHidePopoverOpen(false)
                                        dismissAll()
                                    }}
                                    data-attr="mcp-hint-hide-all"
                                >
                                    Hide all MCP hints
                                </LemonButton>
                            </Tooltip>
                        </div>
                    }
                >
                    <Tooltip title="Hide MCP hints">
                        <button
                            type="button"
                            className={cn(
                                'shrink-0 size-5 inline-flex items-center justify-center rounded',
                                'text-muted hover:text-default hover:bg-fill-button-tertiary-hover',
                                'cursor-pointer bg-transparent border-0 !p-0'
                            )}
                            onClick={() => setHidePopoverOpen((v) => !v)}
                            data-attr="mcp-hint-hide"
                            aria-label="Hide MCP hints"
                        >
                            <IconHide className="size-3.5" />
                        </button>
                    </Tooltip>
                </Popover>
            </div>
        </div>
    )
}
