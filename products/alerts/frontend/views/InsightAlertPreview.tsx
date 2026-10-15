import { IconBell } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

export function InsightAlertPreview({ className }: { className?: string }): JSX.Element {
    return (
        <div className={cn('text-left', className)}>
            <LemonCard hoverEffect={false} className="p-4">
                <div className="flex justify-between gap-2 text-xs text-muted mb-3">
                    <span className="font-semibold">Daily signups</span>
                    <span>Example</span>
                </div>
                <svg
                    viewBox="0 0 400 120"
                    className="w-full h-28"
                    role="img"
                    aria-label="Example: daily signups fall below a threshold of 100 and trigger an alert."
                >
                    <path d="M0 20H400 M0 60H400 M0 100H400" fill="none" className="stroke-border" />
                    <path d="M0 72H400" fill="none" className="stroke-warning" strokeDasharray="6 5" />
                    <text x="4" y="65" className="fill-muted" fontSize="11">
                        Threshold: 100
                    </text>
                    <path
                        d="M0 38L28 32L56 42L84 24L112 33L140 28L168 41L196 30L224 38L252 25L280 35L308 43L336 85L364 91L392 98"
                        fill="none"
                        className="stroke-accent"
                        strokeWidth="3"
                        strokeLinejoin="round"
                        strokeLinecap="round"
                    />
                    <circle cx="336" cy="85" r="6" className="fill-warning stroke-surface-primary" strokeWidth="3" />
                </svg>
                <div className="flex gap-3 items-start border-t pt-3 mt-2">
                    <IconBell className="text-warning text-xl shrink-0 mt-0.5" />
                    <div className="min-w-0 text-sm">
                        <div className="font-semibold">Signups fell below 100</div>
                        <div className="text-muted">Your alert tells you when to take a closer look.</div>
                    </div>
                </div>
            </LemonCard>
        </div>
    )
}
