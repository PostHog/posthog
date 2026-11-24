import { pluralize } from 'lib/utils/strings'

import type { AccountContextSummary } from './accountContextData'
import { AccountContextDate } from './AccountContextDate'

function SummaryCell({ label, value, detail }: { label: string; value: JSX.Element; detail: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 flex-1 min-w-40 border rounded p-3 bg-surface-primary">
            <span className="text-xs text-secondary">{label}</span>
            <span className="text-xl font-semibold">{value}</span>
            <span className="text-xs text-secondary">{detail}</span>
        </div>
    )
}

export function AccountContextSummaryStrip({ summary }: { summary: AccountContextSummary }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-2" data-attr="account-context-summary">
            <SummaryCell
                label="Facts"
                value={<span>{summary.factCount}</span>}
                detail={`${summary.inferredCount} inferred`}
            />
            <SummaryCell
                label="Last capture"
                value={
                    summary.lastCapturedOn ? <AccountContextDate date={summary.lastCapturedOn} /> : <span>None</span>
                }
                detail={`By ${pluralize(summary.writerCount, 'person', 'people')}`}
            />
            <SummaryCell
                label="Open signals"
                value={<span>{summary.openSignalCount}</span>}
                detail={
                    summary.unexplainedSignalCount > 0
                        ? `${summary.unexplainedSignalCount} with no known reason`
                        : 'Each has a known reason'
                }
            />
            <SummaryCell
                label="Needs a recheck"
                value={<span>{summary.recheckCount}</span>}
                detail="Facts past their review date"
            />
        </div>
    )
}
