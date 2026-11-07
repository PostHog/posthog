import { useValues } from 'kea'

import { Button, Collapsible, CollapsibleContent, CollapsibleTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from 'products/signals/frontend/inbox/inboxAnalytics'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { todayReportLogic } from './todayReportLogic'
import { TodayReportSignalRow } from './TodayReportSignalRow'
import { isSampleReportId } from './todaySampleReports'

function EvidenceRows({ reportId }: { reportId: string }): JSX.Element {
    const { shownEvidence } = useValues(todayReportLogic({ reportId }))
    if (shownEvidence.length === 0) {
        return (
            <Text size="sm" variant="muted" render={<p />}>
                No signals are attached to this report yet.
            </Text>
        )
    }
    return (
        <div className="-mx-2 flex flex-col">
            {shownEvidence.map((signal) => (
                <TodayReportSignalRow key={signal.signal_id} reportId={reportId} signal={signal} />
            ))}
        </div>
    )
}

export function TodayReportEvidence({
    report,
    linksToInbox = true,
    defaultCollapsed = false,
}: {
    report: SignalReport
    linksToInbox?: boolean
    defaultCollapsed?: boolean
}): JSX.Element {
    const { shownEvidence, evidenceCount } = useValues(todayReportLogic({ reportId: report.id }))
    const fullReport = urls.inboxReport('reports', report.id)
    const showsSeeAll = linksToInbox && evidenceCount > shownEvidence.length && !isSampleReportId(report.id)

    return (
        <Collapsible
            defaultOpen={!defaultCollapsed}
            onOpenChange={(open) =>
                captureInboxReportAction({
                    report,
                    actionType: open ? 'expand_section' : 'collapse_section',
                    surface: 'today',
                    extra: { section: 'evidence' },
                })
            }
            render={<section aria-label="Evidence" />}
            className="flex flex-col gap-0.5"
            data-attr="today-report-evidence"
        >
            <div className="flex items-baseline justify-between gap-3">
                <Text size="base" weight="semibold" render={<h2 />} className="m-0">
                    <CollapsibleTrigger data-attr="today-report-evidence-toggle">
                        <span>Evidence</span>
                        <Text size="xs" variant="muted" render={<span />}>
                            {evidenceCount}
                        </Text>
                    </CollapsibleTrigger>
                </Text>
                {showsSeeAll && (
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-me-2"
                        nativeButton={false}
                        render={<LinkPrimitive to={fullReport} />}
                        data-attr="today-report-evidence-all"
                    >
                        {`See all ${evidenceCount}`}
                    </Button>
                )}
            </div>
            <CollapsibleContent>
                <EvidenceRows reportId={report.id} />
            </CollapsibleContent>
        </Collapsible>
    )
}
