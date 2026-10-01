import { IconSpinner } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { TodaySessionDot } from './todaySessionDot'

const MARK_CLASS: Record<Exclude<TodaySessionDot['mark'], 'spinner'>, string> = {
    hollow: 'border border-muted-foreground',
    solid: 'bg-primary',
    failed: 'bg-destructive-foreground',
}

export function TodaySessionStatusDot({ dot }: { dot: TodaySessionDot }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={200}
                render={<span className="relative flex size-2 shrink-0 items-center justify-center" />}
            >
                {dot.mark === 'spinner' ? (
                    <span role="img" aria-label={dot.label} className="relative size-2">
                        <IconSpinner className="absolute -inset-0.5 size-3 text-muted-foreground motion-safe:animate-spin" />
                    </span>
                ) : (
                    <span
                        role="img"
                        aria-label={dot.label}
                        className={cn('size-2 rounded-full', MARK_CLASS[dot.mark], dot.faint && 'opacity-40')}
                    />
                )}
                {/* An 8px dot is a small target, so the tooltip also listens on the square around it. */}
                <span aria-hidden className="absolute -inset-2" />
            </TooltipTrigger>
            <TooltipContent side="right">{dot.label}</TooltipContent>
        </Tooltip>
    )
}
