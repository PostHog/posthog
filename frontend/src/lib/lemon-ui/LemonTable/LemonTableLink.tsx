import clsx from 'clsx'
import { ReactNode } from 'react'

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
    /** Clamp the description to two lines instead of rendering it at full height. */
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
    if (!props.to) {
        return (
            <LemonTableLinkContent
                title={title}
                description={description}
                truncateTitle={truncateTitle}
                truncateDescription={truncateDescription}
            />
        )
    }

    return (
        <Link subtle {...props} className={clsx(props.className, truncateTitle && 'block min-w-0')}>
            <LemonTableLinkContent
                title={title}
                description={description}
                truncateTitle={truncateTitle}
                truncateDescription={truncateDescription}
            />
        </Link>
    )
}

function LemonTableLinkContent({
    title,
    description,
    truncateTitle,
    truncateDescription,
}: LemonTableLinkContentProps): JSX.Element {
    return (
        <div className={clsx('flex flex-col py-1', truncateTitle && 'min-w-0')}>
            <div className={clsx('flex flex-row items-center font-semibold text-sm gap-1', truncateTitle && 'min-w-0')}>
                {title}
            </div>

            {description ? (
                <div className={clsx('text-xs text-tertiary mt-1', truncateDescription && 'line-clamp-2')}>
                    {typeof description === 'string' ? (
                        <LemonMarkdown className="max-w-[30rem]" lowKeyHeadings>
                            {description}
                        </LemonMarkdown>
                    ) : (
                        description
                    )}
                </div>
            ) : null}
        </div>
    )
}
