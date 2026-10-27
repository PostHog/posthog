import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { Popover, PopoverContent } from '@posthog/quill'

import type { BetsEntryApi } from '../generated/api.schemas'
import { betsSidebarPreviewLogic } from '../logics/betsSidebarPreviewLogic'
import { BetsSidebarHoverCard } from './BetsSidebarHoverCard'

export function BetsSidebarPreviewCard({ bets, children }: { bets: BetsEntryApi[]; children: ReactNode }): JSX.Element {
    const { previewOpen } = useValues(betsSidebarPreviewLogic)
    const { previewOpenChanged } = useActions(betsSidebarPreviewLogic)
    return (
        <Popover open={previewOpen} onOpenChange={previewOpenChanged}>
            {({ payload }) => {
                const bet = bets.find((candidate) => candidate.id === payload)
                return (
                    <>
                        {children}
                        {bet && (
                            <PopoverContent
                                side="right"
                                align="start"
                                sideOffset={10}
                                initialFocus={false}
                                finalFocus={false}
                                className="w-60 p-0"
                            >
                                <BetsSidebarHoverCard bet={bet} />
                            </PopoverContent>
                        )}
                    </>
                )
            }}
        </Popover>
    )
}
