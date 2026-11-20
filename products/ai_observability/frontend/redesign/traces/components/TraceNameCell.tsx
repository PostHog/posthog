import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { ChipTag } from '../../trace/components/ChipTag'

export interface TraceNameCellProps {
    name: string | null
    href: string
    isSupportTrace: boolean
}

export function TraceNameCell({ name, href, isSupportTrace }: TraceNameCellProps): JSX.Element {
    const label = name ?? 'Untitled trace'
    return (
        <div className="flex max-w-80 min-w-0 items-center gap-1">
            <Link
                to={href}
                title={label}
                className={cn('min-w-0 truncate', name === null ? 'text-muted' : 'font-semibold')}
                // pinned: the drawer's row click recognises this link by it and lets the click through
                data-attr="trace-name-link"
            >
                {label}
            </Link>
            {isSupportTrace ? (
                <ChipTag size="small" type="caution" className="shrink-0">
                    Support
                </ChipTag>
            ) : null}
        </div>
    )
}
