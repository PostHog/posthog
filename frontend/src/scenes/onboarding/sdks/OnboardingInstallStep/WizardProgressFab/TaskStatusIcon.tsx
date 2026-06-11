import { Spinner } from 'lib/lemon-ui/Spinner'

/**
 * Tiny status glyph used in the FAB's expanded task list. The in-progress case
 * gets the live Lemon Spinner; terminal statuses use Unicode symbols sized to
 * the same 14px column.
 */
export function TaskStatusIcon({ status }: { status: string }): JSX.Element {
    if (status === 'in_progress') {
        return (
            <span className="inline-flex items-center justify-center w-3.5 shrink-0 text-brand-red">
                <Spinner textColored speed="0.9s" />
            </span>
        )
    }
    const symbol = status === 'completed' ? '✓' : status === 'failed' ? '✗' : status === 'canceled' ? '⊘' : '☐'
    const color = status === 'completed' ? 'text-success' : status === 'failed' ? 'text-brand-red' : 'text-muted'
    return <span className={`inline-block w-3.5 text-center shrink-0 ${color}`}>{symbol}</span>
}
