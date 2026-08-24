import { type ReactNode } from 'react'

export interface TimelineItem {
    key: string
    /** The dot: any glyph (StepIcon, a spinner, a plain circle). */
    icon: ReactNode
    content: ReactNode
    detail?: ReactNode
}

/**
 * A vertical icon-and-connector rail — the progress card's step list, for both live steps and the
 * upcoming-plan preview. Call sites decide what each dot and row says; the geometry lives here so
 * the preview-to-live swap keeps rows perfectly in place.
 */
export function Timeline({ items, ariaLabel }: { items: TimelineItem[]; ariaLabel?: string }): JSX.Element {
    return (
        <ol className="flex flex-col m-0 p-0 list-none" aria-label={ariaLabel}>
            {items.map((item, i) => (
                <li key={item.key} className="flex gap-3">
                    <div className="flex flex-col items-center pt-0.5">
                        {item.icon}
                        {i < items.length - 1 && <div className="w-px flex-1 bg-border my-1 min-h-[0.75rem]" />}
                    </div>
                    <div className="flex-1 min-w-0 pb-3">
                        {item.content}
                        {item.detail}
                    </div>
                </li>
            ))}
        </ol>
    )
}
