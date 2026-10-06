import { useActions } from 'kea'
import type { ReactNode } from 'react'

import { TodayFigureCard } from './TodayFigureCard'
import { TodayFigureCardContent } from './todayFigureSources'
import { TodayHoverMark } from './TodayHoverMark'
import { TodayPenMark } from './TodayPenMark'
import { circlePath } from './todayPenPaths'
import { todayReportLogic } from './todayReportLogic'

const PEN_DELAY_MS = 250
const PEN_STAGGER_MS = 160

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
    const { markOpened } = useActions(todayReportLogic({ reportId }))
    return (
        <TodayHoverMark
            className="TodayFigureMark"
            dataAttr="today-report-figure"
            onOpen={() => markOpened('impact')}
            card={<TodayFigureCard content={content} figure={figure} reportId={reportId} />}
        >
            <TodayPenMark seed={figure} delayMs={PEN_DELAY_MS + order * PEN_STAGGER_MS}>
                {children}
            </TodayPenMark>
            <svg className="TodayFigureMark__circle" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
                <path d={circlePath(figure)} pathLength={1} />
            </svg>
        </TodayHoverMark>
    )
}
