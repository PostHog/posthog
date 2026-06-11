import { IconNotebook } from '@posthog/icons'

import { SignalReport } from '../../types'
import { ReportCard } from '../cards/ReportCard'

export function ReportsTab({ reports }: { reports: SignalReport[] }): JSX.Element {
    if (reports.length === 0) {
        return (
            <div className="mx-auto max-w-md flex flex-col items-center text-center py-16 px-6 gap-2">
                <div className="flex items-center justify-center h-12 w-12 rounded-full bg-fill-primary text-secondary mb-1">
                    <IconNotebook className="text-2xl" />
                </div>
                <h3 className="text-base font-semibold m-0">No reports yet</h3>
                <p className="text-sm text-tertiary m-0">
                    Reports are what agents surface when there's something worth your judgment but no clean code change
                    to draft.
                </p>
            </div>
        )
    }

    return (
        <div className="mx-auto max-w-4xl flex flex-col gap-3 px-6 py-4">
            {reports.map((report) => (
                <ReportCard key={report.id} report={report} />
            ))}
        </div>
    )
}
