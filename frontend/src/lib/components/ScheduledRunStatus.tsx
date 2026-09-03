import type { ReactNode } from 'react'

import { IconCalendar, IconClock } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

interface NextScheduledRunProps {
    children: ReactNode
    label: string
    loading?: boolean
}

export function NextScheduledRun({ children, label, loading = false }: NextScheduledRunProps): JSX.Element {
    return (
        <div className="text-sm text-muted flex flex-wrap items-center gap-x-2 gap-y-0">
            <IconClock
                className={`size-4 shrink-0 text-muted motion-reduce:animate-none${loading ? ' animate-spin' : ''}`}
                aria-hidden
            />
            <span className="shrink-0">{label}</span>
            {children}
        </div>
    )
}

interface ProjectTimezoneNoticeProps {
    timezone: string
    settingsUrl: string
}

export function ProjectTimezoneNotice({ timezone, settingsUrl }: ProjectTimezoneNoticeProps): JSX.Element {
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
