import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

export function InsightAlertPreview({ className }: { className?: string }): JSX.Element {
    return (
        <div className={cn('text-left', className)}>
            <LemonCard hoverEffect={false} className="p-4">
                <div className="text-sm mb-3">
                    <div className="font-semibold">Daily signups</div>
                    <div className="text-xs text-muted">Example insight</div>
                </div>
                <svg
                    viewBox="0 0 400 120"
                    className="w-full h-20"
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
                <div className="border-t pt-3 mt-2">
                    <div className="text-sm space-y-2">
                        <div className="flex items-center gap-2 font-semibold">
                            <IconSlack className="w-4 h-4 shrink-0" />
                            <span>PostHog</span>
                        </div>
                        <div className="border-l-2 border-warning pl-3 space-y-1">
                            <div className="font-semibold">Signups fell below 100</div>
                            <div>72 signups (lower threshold: 100)</div>
                            <div className="text-link">View insight →</div>
                        </div>
                    </div>
                </div>
            </LemonCard>
        </div>
    )
}
