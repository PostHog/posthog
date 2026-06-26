import { LogsWidgetRow } from '../logs/LogsWidgetRow'
import { logsWidgetSampleLogLines } from '../logs/logsWidgetSampleData'

export function LogsWidgetPreview(): JSX.Element {
    return (
        <div className="flex flex-col divide-y divide-border shadow-sm">
            {logsWidgetSampleLogLines.map((line) => (
                <LogsWidgetRow key={line.uuid} line={line} />
            ))}
        </div>
    )
}
