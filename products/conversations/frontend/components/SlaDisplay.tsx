import clsx from 'clsx'

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

    return (
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
            title={due.format('YYYY-MM-DD HH:mm:ss')}
        >
            {due.fromNow()}
        </span>
    )
}
