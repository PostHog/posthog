import clsx from 'clsx'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

export type SlaState = 'breached' | 'at-risk' | 'on-track'

export function getSlaState(slaDueAt: string): SlaState {
    const diffMs = dayjs(slaDueAt).diff(dayjs())

    if (diffMs < 0) {
        return 'breached'
    }
    if (diffMs < 60 * 60 * 1000) {
        return 'at-risk'
    }
    return 'on-track'
}

export function SlaDisplay({
    slaDueAt,
    className,
    showPopover = true,
}: {
    slaDueAt?: string | null
    className?: string
    showPopover?: boolean
}): JSX.Element | null {
    if (!slaDueAt) {
        return null
    }

    const due = dayjs(slaDueAt)
    const slaState = getSlaState(slaDueAt)

    return (
        <TZLabel
            time={due}
            showPopover={showPopover}
            className={clsx(
                'font-medium',
                {
                    'text-danger': slaState === 'breached',
                    'text-warning': slaState === 'at-risk',
                    'text-success': slaState === 'on-track',
                },
                className
            )}
        />
    )
}
