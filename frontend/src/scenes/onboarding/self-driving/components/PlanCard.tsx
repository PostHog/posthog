import { type ReactNode } from 'react'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'

/**
 * One plan option: header (name + price), body, footnote, and a bottom-pinned CTA. The two plan
 * cards differ only in this data plus whether they carry the accent border, so the shape lives here
 * and the call sites read as content.
 */
export function PlanCard({
    title,
    titleCaption,
    priceLabel,
    highlighted = false,
    footnote,
    cta,
    children,
}: {
    title: string
    /** Small line under the title (e.g. "Free allowance included"). */
    titleCaption?: string
    /** Right-aligned price text in the header. */
    priceLabel?: string | null
    /** Accent border, for the plan we want the eye on. */
    highlighted?: boolean
    footnote?: string
    cta: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} focused={highlighted} className={cn('flex flex-1 basis-72 flex-col gap-3 p-4')}>
            <div className="flex items-baseline justify-between gap-2">
                <div>
                    <p className="m-0 text-base font-semibold">{title}</p>
                    {titleCaption && <p className="m-0 text-xs text-muted">{titleCaption}</p>}
                </div>
                {priceLabel && <p className="m-0 text-sm text-muted">{priceLabel}</p>}
            </div>
            {children}
            {footnote && <p className="m-0 text-xs text-muted">{footnote}</p>}
            <div className="mt-auto">{cta}</div>
        </LemonCard>
    )
}
