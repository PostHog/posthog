import { useState } from 'react'

import { cn } from 'lib/utils/css-classes'

import { Logomark } from './Logomark'

const LOGOMARK_AIRTIME_MS = 400 // Sync with --logomark-airtime in base.scss

interface LogomarkJumpCSSProperties extends React.CSSProperties {
    '--logomark-jump-magnitude': number
}

/**
 * The PostHog logomark that springs up when clicked – rapid repeat clicks escalate the jump. Used as
 * the playful mascot in the PostHog AI (Max) intro and the Inbox self-driving onboarding.
 */
export function JumpingLogomark({ className }: { className?: string }): JSX.Element {
    const [lastJumped, setLastJumped] = useState<number | null>(() => Date.now())
    const [jumpIteration, setJumpIteration] = useState(0)

    const handleClick = (): void => {
        const now = Date.now()
        if (lastJumped && now - lastJumped < LOGOMARK_AIRTIME_MS) {
            return // Don't interrupt an in-flight jump.
        }
        setJumpIteration(jumpIteration + 1)
        setLastJumped(null)
        requestAnimationFrame(() => setLastJumped(now))
    }

    return (
        <div
            className={cn('cursor-pointer select-none', lastJumped && 'animate-logomark-jump', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--logomark-jump-magnitude': jumpIteration ? 1.5 ** ((jumpIteration % 8) - 2) : 1,
                } as LogomarkJumpCSSProperties
            }
            onClick={handleClick}
        >
            <Logomark />
        </div>
    )
}
