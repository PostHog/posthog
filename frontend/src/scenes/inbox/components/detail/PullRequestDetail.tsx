import { SignalReport } from '../../types'
import { ReportDetail } from './ReportDetail'

/**
 * Pull request detail is now the unified `ReportDetail`, which renders the PR banner +
 * "Open in GitHub" action whenever the report has a shipped implementation PR. Kept as a
 * thin alias for back-compat (e.g. stories / any external imports).
 */
export function PullRequestDetail({ report }: { report: SignalReport }): JSX.Element {
    return <ReportDetail report={report} tab="pulls" />
}
