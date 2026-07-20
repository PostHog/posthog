import { ReactNode } from 'react'

import { IconCalendar, IconClock } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

interface AlertDefinitionRowProps {
    label?: ReactNode
    children: ReactNode
    className?: string
}

export function AlertDefinitionRow({ label, children, className }: AlertDefinitionRowProps): JSX.Element {
    return (
        <div className={`flex flex-wrap gap-x-3 gap-y-2 items-center${className ? ` ${className}` : ''}`}>
            {label ? <div>{label}</div> : null}
            {children}
        </div>
    )
}

interface AlertNextEvaluationStatusProps {
    children: ReactNode
    loading?: boolean
}

export function AlertNextEvaluationStatus({ children, loading = false }: AlertNextEvaluationStatusProps): JSX.Element {
    return (
        <div className="text-sm text-muted flex flex-wrap items-center gap-x-2 gap-y-0">
            <IconClock
                className={`size-4 shrink-0 text-muted motion-reduce:animate-none${loading ? ' animate-spin' : ''}`}
                aria-hidden
            />
            <span className="shrink-0">Next planned evaluation:</span>
            {children}
        </div>
    )
}

interface AlertTimezoneNoticeProps {
    timezone: string
    settingsUrl: string
}

export function AlertTimezoneNotice({ timezone, settingsUrl }: AlertTimezoneNoticeProps): JSX.Element {
    return (
        <div className="text-muted text-sm flex flex-wrap items-start gap-2">
            <IconCalendar className="size-4 shrink-0 text-muted mt-0.5" aria-hidden />
            <span className="min-w-0">
                Times use your project timezone ({timezone}).{' '}
                <Link to={settingsUrl} target="_blank" targetBlankIcon={false}>
                    Change in settings
                </Link>
            </span>
        </div>
    )
}
