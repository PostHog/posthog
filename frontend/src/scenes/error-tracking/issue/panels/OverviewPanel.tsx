import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getExceptionAttributes } from 'scenes/error-tracking/utils'

export const OverviewPanel = (): JSX.Element => {
    const { issueProperties, issueLoading } = useValues(errorTrackingIssueSceneLogic)

    const { synthetic, level, browser, os, library, unhandled } = getExceptionAttributes(issueProperties)

    const TableRow = ({ label, value }: { label: string; value: string | undefined }): JSX.Element => (
        <tr>
            <td className="text-muted">{label}</td>
            <td>{value ?? <div className="italic">unknown</div>}</td>
        </tr>
    )

    if (issueLoading) {
        return (
            <div className="space-y-2">
                <LemonSkeleton />
                <LemonSkeleton.Row repeat={2} />
            </div>
        )
    }

    return (
        <div className="px-1">
            <div className="grid grid-cols-2 gap-2">
                <table>
                    {[
                        { label: 'Level', value: level },
                        { label: 'Synthetic', value: synthetic },
                        { label: 'Library', value: library },
                        { label: 'Unhandled', value: unhandled },
                    ].map((row, index) => (
                        <TableRow key={index} {...row} />
                    ))}
                </table>
                <table>
                    {[
                        { label: 'Browser', value: browser },
                        { label: 'OS', value: os },
                        { label: 'URL', value: issueProperties['$current_url'] },
                    ].map((row, index) => (
                        <TableRow key={index} {...row} />
                    ))}
                </table>
            </div>
        </div>
    )
}
