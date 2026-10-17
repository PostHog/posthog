import { forwardRef } from 'react'

import { Card, CardContent, cn } from '@posthog/quill'

import { SidePanelTab } from '~/types'

import { TodayContextPanelContent } from './TodayContextPanelContent'
import { TodayContextPanelHeader } from './TodayContextPanelHeader'

interface TodayContextPanelCardProps {
    docked: boolean
    tab: SidePanelTab
    onDragStart?: (event: React.PointerEvent<HTMLDivElement>) => void
    className?: string
}

export const TodayContextPanelCard = forwardRef<HTMLDivElement, TodayContextPanelCardProps>(
    function TodayContextPanelCard({ docked, tab, onDragStart, className }, ref) {
        return (
            // The header carries its own padding, so the card drops its top padding too. The panels paint the
            // app's surface, so the card takes the same one and the header and body read as one surface. The
            // radius and the border are the Today frame's, so the card's edges match the content and the floating
            // sidebar.
            <Card
                ref={ref}
                flush
                className={cn(
                    'min-h-0 rounded-[var(--today-frame-radius)] border border-border bg-[var(--color-bg-surface-primary)] pt-0 shadow-none',
                    className
                )}
                data-attr="today-context-panel-card"
            >
                <TodayContextPanelHeader docked={docked} onDragStart={onDragStart} />
                <CardContent className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    <TodayContextPanelContent tab={tab} />
                </CardContent>
            </Card>
        )
    }
)
