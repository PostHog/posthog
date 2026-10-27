import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TodaySessionStatusDot } from '~/layout/today/TodaySessionStatusDot'

import type { BetsEntryApi } from '../generated/api.schemas'
import { betGlyph } from '../lib/betStatus'
import { BetWorkStatusIcon } from './BetWorkStatusIcon'

export function BetsStatusGlyph({ bet }: { bet: Pick<BetsEntryApi, 'status' | 'needs_you'> }): JSX.Element {
    const glyph = betGlyph(bet)
    if (glyph.mark !== 'spinner') {
        return <TodaySessionStatusDot dot={glyph} />
    }
    return (
        <Tooltip>
            <TooltipTrigger
                delay={200}
                render={
                    <span
                        role="img"
                        aria-label={glyph.label}
                        className="flex size-3.5 shrink-0 items-center justify-center text-muted-foreground"
                    />
                }
            >
                <BetWorkStatusIcon status={{ label: glyph.label, mark: 'spinner' }} />
            </TooltipTrigger>
            <TooltipContent side="right">{glyph.label}</TooltipContent>
        </Tooltip>
    )
}
