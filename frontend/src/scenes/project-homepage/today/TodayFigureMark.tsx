import { PreviewCard } from '@base-ui/react/preview-card'
import { type ReactNode, useState } from 'react'

import { Card } from '@posthog/quill'

import { TodayFigureCard } from './TodayFigureCard'
import {
    HOVER_CARD_GAP_PX,
    HOVER_CLOSE_DELAY_MS,
    HOVER_OPEN_DELAY_MS,
    cardAnchor,
    pointerMovedRecently,
} from './todayHoverCard'
import { circlePath } from './todayPenPaths'
import { TodayPenStroke } from './TodayPenStroke'
import { TodayFigureCardContent } from './todayReportPresentation'

export function TodayFigureMark({
    children,
    figure,
    content,
    reportId,
    order,
}: {
    children: ReactNode
    figure: string
    content: TodayFigureCardContent
    reportId: string
    order: number
}): JSX.Element {
    const [trigger, setTrigger] = useState<HTMLElement | null>(null)
    const [open, setOpen] = useState(false)
    const delayMs = 250 + order * 160
    return (
        // A tap opens the card too, so the evidence is not mouse-only.
        <PreviewCard.Root
            open={open}
            onOpenChange={(next, details) => {
                if (next && details.reason === 'trigger-hover' && !pointerMovedRecently()) {
                    return
                }
                setOpen(next)
            }}
        >
            <PreviewCard.Trigger
                delay={HOVER_OPEN_DELAY_MS}
                closeDelay={HOVER_CLOSE_DELAY_MS}
                ref={setTrigger}
                render={<span tabIndex={0} />}
                onClick={() => setOpen(true)}
                className="TodayMark"
                data-attr="today-report-figure"
            >
                {children}
                <TodayPenStroke seed={figure} delayMs={delayMs} />
                <svg className="TodayMark__circle" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
                    <path d={circlePath(figure)} pathLength={1} />
                </svg>
            </PreviewCard.Trigger>
            <PreviewCard.Portal>
                <PreviewCard.Positioner
                    data-quill
                    data-quill-portal="popover"
                    className="[--quill-z-popover:var(--z-popover-with-chart)]"
                    anchor={cardAnchor(trigger)}
                    side="bottom"
                    align="start"
                    sideOffset={HOVER_CARD_GAP_PX}
                >
                    <PreviewCard.Popup className="TodayEvidencePopup outline-none">
                        <Card
                            size="sm"
                            className="TodayEvidenceCard w-[var(--anchor-width)] gap-0 border border-border py-0"
                        >
                            <TodayFigureCard content={content} figure={figure} reportId={reportId} />
                        </Card>
                    </PreviewCard.Popup>
                </PreviewCard.Positioner>
            </PreviewCard.Portal>
        </PreviewCard.Root>
    )
}
