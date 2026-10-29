import { IconArchive, IconCheck, IconClock, IconWarning, IconX } from '@posthog/icons'

import type { BetWorkStatus } from '../lib/workStatus'

export function BetWorkStatusIcon({ status }: { status: BetWorkStatus }): JSX.Element {
    if (status.mark === 'spinner') {
        return (
            <span className="inline-grid size-3.5 place-items-center font-mono text-sm leading-none">
                {['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'].map((frame, index) => (
                    <span key={frame} className="Bets__statusFrame" style={{ animationDelay: `${index * 80}ms` }}>
                        {frame}
                    </span>
                ))}
            </span>
        )
    }
    const icon =
        status.mark === 'verified' ? (
            <IconCheck className="text-success" />
        ) : status.mark === 'failed' || status.mark === 'cancelled' ? (
            <IconX />
        ) : status.mark === 'waiting' ? (
            <IconClock />
        ) : status.mark === 'attention' ? (
            <IconWarning className="text-warning" />
        ) : status.mark === 'previous' ? (
            <IconArchive />
        ) : (
            <span className="size-2 rounded-full border border-current" />
        )
    return <span className="inline-flex size-3.5 items-center justify-center [&>svg]:size-3.5">{icon}</span>
}
