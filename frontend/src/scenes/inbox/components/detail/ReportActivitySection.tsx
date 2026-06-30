import { useValues } from 'kea'

import { IconClockRewind } from '@posthog/icons'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { ArtefactLogList } from './ArtefactLogList'
import { RightColumnSection } from './DetailSection'

/**
 * The report's chronological work-log: every artefact (judgments, findings, code references, diffs,
 * commits, task runs, notes, reviewers) rendered as a timeline entry. Reads the artefacts the detail
 * logic already loads (and polls while the report is active), so it stays in sync with the rest of
 * the detail view. Hidden entirely until at least one artefact exists. Mirrors desktop
 * `ReportActivitySection`.
 */
export function ReportActivitySection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportArtefacts, reportTasks } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))

    if (!reportArtefacts || reportArtefacts.length === 0) {
        return null
    }

    // The logic already resolved the research/implementation tasks; hand them to the `task_run` rows
    // so they don't re-fetch the same tasks the Runs section just loaded.
    const knownTasks = new Map((reportTasks ?? []).map((entry) => [entry.task.id, entry.task]))

    return (
        <RightColumnSection
            icon={<IconClockRewind />}
            title="Activity"
            collapsible
            defaultCollapsed
            rightSlot={
                <span className="text-[0.6875rem] text-tertiary tabular-nums">
                    {reportArtefacts.length} {reportArtefacts.length === 1 ? 'entry' : 'entries'}
                </span>
            }
        >
            <ArtefactLogList reportId={report.id} artefacts={reportArtefacts} knownTasks={knownTasks} />
        </RightColumnSection>
    )
}
