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
}

export function LemonTableLink({
    title,
    description,
    truncateTitle,
    ...props
}: Pick<LinkProps, 'to' | 'onClick' | 'target' | 'className' | 'targetBlankIcon'> &
    LemonTableLinkContentProps): JSX.Element {
    if (!props.to) {
        if (props.onClick) {
            return (
                <Link subtle onClick={props.onClick} className={clsx(props.className, truncateTitle && 'block min-w-0')}>
                    <LemonTableLinkContent title={title} description={description} truncateTitle={truncateTitle} />
                </Link>
            )
        }
        return <LemonTableLinkContent title={title} description={description} truncateTitle={truncateTitle} />
    }

    return (
        <Link subtle {...props} className={clsx(props.className, truncateTitle && 'block min-w-0')}>
            <LemonTableLinkContent title={title} description={description} truncateTitle={truncateTitle} />
        </Link>
    )
}
