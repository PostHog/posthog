import { useEffect, useState } from 'react'

import { inStorybookTestRunner } from 'lib/utils/dom'

/** Below this a turn feels immediate, and a counter is just noise. */
const SHOW_AFTER_MS = 5000

function formatElapsed(elapsedMs: number): string {
    const totalSeconds = Math.floor(elapsedMs / 1000)
    if (totalSeconds < 60) {
        return `${totalSeconds}s`
    }
    return `${Math.floor(totalSeconds / 60)}m ${String(totalSeconds % 60).padStart(2, '0')}s`
}

/**
 * Live "we're still working" counter for the composer. Answers can take minutes, and a static
 * placeholder plus a rotating adjective is indistinguishable from a hung chat — people give up on
 * turns that do eventually finish.
 */
export function ThinkingElapsed({ startedAt }: { startedAt: number | null }): JSX.Element | null {
    // A ticking clock would make every story snapshot depend on when it was captured.
    const disabled = startedAt === null || inStorybookTestRunner()
    const [now, setNow] = useState(() => Date.now())

    useEffect(() => {
        if (disabled) {
            return
        }
        const interval = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(interval)
    }, [disabled, startedAt])

    if (disabled || startedAt === null) {
        return null
    }
    const elapsedMs = now - startedAt
    if (elapsedMs < SHOW_AFTER_MS) {
        return null
    }
    return <span className="text-tertiary tabular-nums">{formatElapsed(elapsedMs)}</span>
}
