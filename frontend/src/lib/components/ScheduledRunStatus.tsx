import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCalendar, IconClock } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { shortTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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

/** Inline project timezone abbreviation, e.g. "(PST)", with a tooltip linking to settings. */
export function ProjectTimezoneHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    if (!currentTeam) {
        return null
    }
    const tz = shortTimeZone(currentTeam.timezone) ?? currentTeam.timezone
    return (
        <Tooltip
            interactive
            title={
                <>
                    Times are in the{' '}
                    <Link to={urls.settings('environment-customization', 'date-and-time')} target="_blank">
                        project's timezone
                    </Link>{' '}
                    ({currentTeam.timezone})
                </>
            }
        >
            <span className="text-muted font-normal">({tz})</span>
        </Tooltip>
    )
}
