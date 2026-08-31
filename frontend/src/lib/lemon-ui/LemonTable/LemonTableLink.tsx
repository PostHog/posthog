import clsx from 'clsx'
import { ReactNode, useEffect, useRef, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'

import { LemonMarkdown } from '../LemonMarkdown'
import { Link, LinkProps } from '../Link'

interface LemonTableLinkContentProps {
    title: JSX.Element | string
    description?: ReactNode
    /**
     * Let the title shrink and truncate (with an ellipsis) when the cell is narrower than the content,
     * instead of overflowing. The title itself must carry a `truncate` class for the ellipsis to show.
     */
    truncateTitle?: boolean
    /** Clamp the description to two lines, with a "Show more" toggle when it overflows. */
    truncateDescription?: boolean
}

export function LemonTableLink({
    title,
    description,
    truncateTitle,
    truncateDescription,
    ...props
}: Pick<LinkProps, 'to' | 'onClick' | 'target' | 'className' | 'targetBlankIcon'> &
    LemonTableLinkContentProps): JSX.Element {
    const titleRow = (
        <div className={clsx('flex flex-row items-center font-semibold text-sm gap-1', truncateTitle && 'min-w-0')}>
            {title}
        </div>
    )
    const descriptionBlock = description ? (
        // Keyed by the text so a row reused for a different record (LemonTable falls back to index
        // keys) doesn't carry over the previous record's expanded state.
        <LemonTableLinkDescription
            key={typeof description === 'string' ? description : undefined}
            description={description}
            truncate={truncateDescription}
        />
    ) : null

    if (!props.to) {
        return (
            <div className={clsx('flex flex-col py-1', truncateTitle && 'min-w-0')}>
                {titleRow}
                {descriptionBlock}
            </div>
        )
    }

    if (truncateDescription) {
        // The "Show more" toggle is a button, which can't nest inside the anchor, so a clamped
        // description sits next to the link instead of inside it.
        return (
            <div className={clsx('flex flex-col py-1', truncateTitle && 'min-w-0')}>
                <Link subtle {...props} className={clsx(props.className, truncateTitle && 'block min-w-0')}>
                    {titleRow}
                </Link>
                {descriptionBlock}
            </div>
        )
    }

    return (
        <Link subtle {...props} className={clsx(props.className, truncateTitle && 'block min-w-0')}>
            <div className={clsx('flex flex-col py-1', truncateTitle && 'min-w-0')}>
                {titleRow}
                {descriptionBlock}
            </div>
        </Link>
    )
}

function LemonTableLinkDescription({
    description,
    truncate,
}: {
    description: ReactNode
    truncate?: boolean
}): JSX.Element {
    const contentRef = useRef<HTMLDivElement | null>(null)
    const [expanded, setExpanded] = useState(false)
    const [isOverflowing, setIsOverflowing] = useState(false)
    // The column resizes with the scene (e.g. opening a side panel), which changes the line count.
    const { width: contentWidth } = useResizeObserver({ ref: contentRef })

    useEffect(() => {
        if (truncate && !expanded && contentRef.current) {
            setIsOverflowing(contentRef.current.scrollHeight > contentRef.current.clientHeight)
        }
    }, [truncate, expanded, description, contentWidth])

    return (
        <div className="text-xs text-tertiary mt-1">
            <div ref={contentRef} className={clsx(truncate && !expanded && 'line-clamp-2')}>
                {typeof description === 'string' ? (
                    <LemonMarkdown className="max-w-[30rem]" lowKeyHeadings disableImages>
                        {description}
                    </LemonMarkdown>
                ) : (
                    description
                )}
            </div>
            {truncate && (isOverflowing || expanded) && (
                <Link
                    onClick={() => setExpanded(!expanded)}
                    className="text-xs"
                    aria-expanded={expanded}
                    data-attr="lemon-table-link-description-toggle"
                >
                    {expanded ? 'Show less' : 'Show more'}
                </Link>
            )}
        </div>
    )
}
