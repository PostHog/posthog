import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconSparkles } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { AgentBadgeRotator } from './AgentBadgeRotator'
import { mcpHintLogic } from './mcpHintLogic'
import { MCPInstallCommand } from './MCPInstallCommand'
import { getSurfacePrompts, type SurfaceKey } from './prompts'

const FIRST_SEEN_KEY_PREFIX = 'mcp-use-case-card-first-seen:'

function getExpiryState(surfaceKey: SurfaceKey, expiresAfterMs: number): { expired: boolean; firstSeenAt: number } {
    const key = FIRST_SEEN_KEY_PREFIX + surfaceKey
    const stored = localStorage.getItem(key)
    if (stored) {
        const firstSeenAt = parseInt(stored, 10)
        return { expired: Date.now() - firstSeenAt > expiresAfterMs, firstSeenAt }
    }
    const now = Date.now()
    localStorage.setItem(key, String(now))
    return { expired: false, firstSeenAt: now }
}

export function MCPUseCaseCard({
    surfaceKey,
    className,
    /**
     * If set, the card hides itself after this many ms have passed since the first time it appeared
     * for this user (per-surface, persisted in localStorage). Use in contexts that aren't a one-shot
     * empty state (e.g. the SQL editor, which a user revisits often).
     */
    expiresAfterMs,
    // Force display, only useful in storybook to simplify flags
    forceDisplay = false,
}: {
    surfaceKey: SurfaceKey
    className?: string
    expiresAfterMs?: number
    forceDisplay?: boolean
}): JSX.Element | null {
    const { effectiveOptOut, userRole, topEvents } = useValues(mcpHintLogic)
    const { loadTopEvents } = useActions(mcpHintLogic)
    const [expired] = useState(() => (expiresAfterMs ? getExpiryState(surfaceKey, expiresAfterMs).expired : false))
    const triedLoadingEvents = useRef(false)

    const willRender = forceDisplay || (!effectiveOptOut && !expired)

    useEffect(() => {
        // Only the SQL editor surface benefits from the team's real event names — keep the call narrow.
        // Fetch at most once per mount; a failed call returns [] and must not retry on re-render.
        if (willRender && surfaceKey === 'sql.execute' && !triedLoadingEvents.current) {
            triedLoadingEvents.current = true
            loadTopEvents()
        }
    }, [willRender, surfaceKey, loadTopEvents])

    if (!willRender) {
        return null
    }

    const { examples } = getSurfacePrompts(surfaceKey, { role: userRole, topEvents })

    return (
        <div
            className={cn(
                'mt-6 rounded-lg border border-dashed border-primary bg-bg-light p-4 flex flex-col gap-3',
                className
            )}
        >
            <div className="flex items-center gap-2">
                <IconSparkles className="size-4 shrink-0" />
                <h4 className="m-0 text-sm font-semibold">Or do it from your agent</h4>
            </div>
            <div className="text-sm text-default">
                Ask <AgentBadgeRotator />:
            </div>
            <ul className="m-0 pl-5 list-disc text-xs text-muted leading-relaxed">
                {examples.map((example) => (
                    <li key={example}>{example}</li>
                ))}
            </ul>
            <div className="pt-1">
                <MCPInstallCommand size="sm" />
            </div>
        </div>
    )
}
