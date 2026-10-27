import { Popover, PopoverContent, PopoverTrigger, cn } from '@posthog/quill'

import { TodayPaneOption } from '~/layout/today/TodayPaneOption'

import type { BetsEntryApi } from '../generated/api.schemas'
import { betPerformance } from '../lib/betPerformance'
import { compactMoney } from '../lib/format'
import { BET_RATING_CLASSES } from './betRatingClasses'
import { BetsSidebarHoverCard } from './BetsSidebarHoverCard'

const OPEN_DELAY_MS = 400
const CLOSE_DELAY_MS = 100

interface BetsSidebarRowProps {
    bet: BetsEntryApi
    to: string
    active: boolean
}

export function BetsSidebarRow({ bet, to, active }: BetsSidebarRowProps): JSX.Element {
    const performance = betPerformance(bet)
    return (
        <Popover>
            <PopoverTrigger
                openOnHover
                delay={OPEN_DELAY_MS}
                closeDelay={CLOSE_DELAY_MS}
                nativeButton={false}
                render={<div className="min-w-0" />}
            >
                <TodayPaneOption value={bet.id} to={to} active={active} data-attr="bets-sidebar-bet">
                    <span className="min-w-0 flex-1 truncate">{bet.title}</span>
                    <span
                        className={cn(
                            'shrink-0 text-xs font-normal tabular-nums',
                            performance ? BET_RATING_CLASSES[performance.rating] : 'text-muted-foreground'
                        )}
                    >
                        {compactMoney(bet.money.spent_cents)}
                    </span>
                </TodayPaneOption>
            </PopoverTrigger>
            <PopoverContent side="right" align="start" sideOffset={10} initialFocus={false} className="w-60 p-0">
                <BetsSidebarHoverCard bet={bet} />
            </PopoverContent>
        </Popover>
    )
}
