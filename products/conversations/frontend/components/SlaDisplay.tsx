import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

export function SlaDisplay({
    slaDueAt,
    className,
}: {
    slaDueAt?: string | null
    className?: string
}): JSX.Element | null {
    if (!slaDueAt) {
        return null
    }

    const due = dayjs(slaDueAt)
    const diffMs = due.diff(dayjs())
    const breached = diffMs < 0
    const atRisk = !breached && diffMs < 60 * 60 * 1000

    // Use the styled lemon-ui Tooltip rather than the native `title` attribute,
    // which the browser is slow to pop on hover and can't be styled to match.
    return (
        <Tooltip title={`SLA due ${due.format('YYYY-MM-DD HH:mm:ss')}`}>
            <span
                className={clsx(
                    'font-medium',
                    {
                        'text-danger': breached,
                        'text-warning': atRisk,
                        'text-success': !breached && !atRisk,
                    },
                    className
                )}
            >
                {due.fromNow()}
            </span>
        </Tooltip>
    )
}
