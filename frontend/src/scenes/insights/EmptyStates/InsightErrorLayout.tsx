import type { ReactNode } from 'react'

export function InsightErrorLayout({
    illustration,
    title,
    detail,
    actions,
    footer,
}: {
    illustration: JSX.Element
    title: string | JSX.Element
    detail?: ReactNode
    actions?: ReactNode
    footer?: ReactNode
}): JSX.Element {
    // pinned: tests, stories and autocapture select on both data-attr values, so do not rename them
    return (
        <div
            data-attr="insight-empty-state"
            className="flex flex-1 min-h-0 flex-col items-center justify-center rounded px-4 py-6 w-full text-center text-balance"
        >
            {illustration}
            <h2 data-attr="insight-loading-too-long" className="text-xl leading-tight text-danger mt-4 mb-0">
                {title}
            </h2>
            {/* *:mb-0 removes the global paragraph margin, so the next step stays directly under the title */}
            <div className="flex flex-col items-center gap-1 mt-1 max-w-120 text-sm text-tertiary *:mb-0 empty:hidden">
                {detail}
            </div>
            <div className="flex flex-wrap justify-center gap-2 mt-4 empty:hidden">{actions}</div>
            <div className="flex flex-col items-center gap-1 mt-3 empty:hidden">{footer}</div>
        </div>
    )
}
