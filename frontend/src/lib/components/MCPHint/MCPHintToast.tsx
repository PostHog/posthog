import { useActions } from 'kea'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { AgentBadgeRotator } from './AgentBadgeRotator'
import { mcpHintLogic } from './mcpHintLogic'
import { MCPInstallCommand } from './MCPInstallCommand'
import { SURFACE_PROMPTS, type SurfaceKey } from './prompts'

const linkClass =
    'text-xs text-muted hover:text-default underline underline-offset-2 cursor-pointer bg-transparent border-0 !p-0 !m-0'

export function MCPHintToast({ surfaceKey }: { surfaceKey: SurfaceKey }): JSX.Element {
    const { dismissSurface, dismissAll } = useActions(mcpHintLogic)
    const [showHideOptions, setShowHideOptions] = useState(false)

    const prompt = SURFACE_PROMPTS[surfaceKey].toast

    return (
        <div className="flex flex-col gap-1 py-1 pr-1 text-default min-w-0 items-start">
            <div className="flex items-center gap-1.5 text-sm">
                <IconSparkles className="size-4 shrink-0" />
                <span>
                    Next time, ask <AgentBadgeRotator /> to do it for you:
                </span>
            </div>
            <div className="text-xs italic text-muted leading-snug">{prompt}</div>
            <MCPInstallCommand size="sm" className="mt-1" />
            <div className="flex items-baseline flex-wrap">
                <button
                    type="button"
                    className={linkClass}
                    onClick={() => setShowHideOptions((v) => !v)}
                    data-attr="mcp-hint-hide"
                >
                    Hide{showHideOptions ? <>&nbsp;&gt;&nbsp;</> : <>&nbsp;MCP hints</>}
                </button>
                {showHideOptions && (
                    <div className="flex items-baseline gap-0.5 ml-1.5">
                        <Tooltip title="Stop suggesting MCP for this kind of action. You'll still see hints for other actions, at most once a week.">
                            <button
                                type="button"
                                className={linkClass}
                                onClick={() => dismissSurface(surfaceKey)}
                                data-attr="mcp-hint-hide-surface"
                            >
                                this hint
                            </button>
                        </Tooltip>
                        <span className="text-xs text-muted">/</span>
                        <Tooltip title="Turn off MCP hints everywhere. If you keep them on, you'll only see one at most per week.">
                            <button
                                type="button"
                                className={cn(linkClass, '!text-danger hover:!opacity-80')}
                                onClick={() => dismissAll()}
                                data-attr="mcp-hint-hide-all"
                            >
                                all MCP hints
                            </button>
                        </Tooltip>
                    </div>
                )}
            </div>
        </div>
    )
}
