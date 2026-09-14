import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { ticketPatternAiScanLogic } from '../../components/TicketPatterns/ticketPatternAiScanLogic'

export function TicketPatternAiScanFindings(): JSX.Element | null {
    const { status, statusLoading, reports, reportsLoading } = useValues(ticketPatternAiScanLogic)
    const { loadReports } = useActions(ticketPatternAiScanLogic)

    useEffect(() => {
        loadReports()
    }, [loadReports])

    // The section exists once a scout has ever been made, even while paused, so its old findings stay reachable.
    if (!status?.skill_name) {
        return null
    }

    const scoutUrl = urls.inboxScout(status.skill_name)

    return (
        <SceneSection
            title="AI scan findings"
            titleSize="sm"
            description={
                status.enabled
                    ? 'What the hourly AI scan found in the new tickets, newest first.'
                    : 'The AI scan is off. Turn it on in settings to get new findings.'
            }
            actions={
                <LemonButton size="small" type="secondary" to={scoutUrl}>
                    Open scout in Inbox
                </LemonButton>
            }
        >
            {statusLoading || reportsLoading ? (
                <LemonSkeleton className="h-10 w-full" repeat={2} />
            ) : reports.length === 0 ? (
                <p className="text-muted text-sm mb-0">
                    {status.enabled
                        ? 'Nothing yet. The scout files a finding only when it sees an outage or a bug across several customers.'
                        : 'No findings were filed while the scan was on.'}
                </p>
            ) : (
                <ul className="flex flex-col gap-2 mb-0">
                    {reports.map((report) => (
                        <li key={report.report_id} className="flex flex-col gap-0.5 min-w-0">
                            <div className="flex flex-wrap items-baseline gap-x-2">
                                <Link
                                    to={urls.inboxReport('reports', report.report_id)}
                                    className="font-semibold truncate min-w-0"
                                >
                                    {report.title}
                                </Link>
                                <TZLabel time={report.filed_at} className="text-muted text-xs" />
                            </div>
                            <span className="text-muted text-xs break-words">{report.summary}</span>
                        </li>
                    ))}
                </ul>
            )}
        </SceneSection>
    )
}
