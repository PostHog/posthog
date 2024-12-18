import { useValues } from 'kea'
import { errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { getExceptionAttributes } from 'scenes/error-tracking/utils'

export const OverviewPanel = (): JSX.Element => {
    const { issueProperties } = useValues(errorTrackingIssueSceneLogic)

    const { synthetic, level, browser, os, library } = getExceptionAttributes(issueProperties)

    const unknown = <div className="italic">unknown</div>

    const TableRow = ({ label, value }: { label: string; value: string | undefined }): JSX.Element => (
        <tr>
            <td className="text-muted">{label}</td>
            <td>{value ?? unknown}</td>
        </tr>
    )

    return (
        <div className="px-1">
            <div className="grid grid-cols-2 gap-2">
                <table>
                    {[
                        { label: 'Level', value: level },
                        { label: 'Synthetic', value: synthetic },
                        { label: 'Library', value: library },
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
