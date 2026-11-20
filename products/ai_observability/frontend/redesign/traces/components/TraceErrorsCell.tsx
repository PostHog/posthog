import { ChipTag } from '../../trace/components/ChipTag'

export interface TraceErrorsCellProps {
    firstError: string | null
    errorCount: number
    hasError: boolean
}

export function TraceErrorsCell({ firstError, errorCount, hasError }: TraceErrorsCellProps): JSX.Element | null {
    if (!hasError) {
        return null
    }
    const message = firstError ?? 'Unknown error'
    const otherErrors = errorCount - 1
    return (
        <div className="flex max-w-60 min-w-0 items-center gap-1">
            <ChipTag type="danger" size="small" title={message} className="min-w-0">
                <span className="truncate">{message}</span>
            </ChipTag>
            {otherErrors > 0 ? <span className="shrink-0 text-xs text-secondary">+{otherErrors}</span> : null}
        </div>
    )
}
