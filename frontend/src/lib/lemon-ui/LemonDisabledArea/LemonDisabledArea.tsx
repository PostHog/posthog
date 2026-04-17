import './LemonDisabledArea.scss'

import clsx from 'clsx'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export interface LemonDisabledAreaProps extends React.HTMLAttributes<HTMLDivElement> {
    disabledReason?: string | null | false
}

export function LemonDisabledArea({
    children,
    className,
    disabledReason,
    onClick,
    ...props
}: LemonDisabledAreaProps): JSX.Element {
    const content = (
        <div
            className={clsx('LemonDisabledArea', disabledReason && 'LemonDisabledArea--disabled', className)}
            aria-disabled={!!disabledReason}
            onClick={disabledReason ? undefined : onClick}
            {...props}
        >
            {children}
        </div>
    )

    return disabledReason ? (
        <Tooltip title={<i>{disabledReason}</i>} placement="top-start">
            {content}
        </Tooltip>
    ) : (
        content
    )
}
