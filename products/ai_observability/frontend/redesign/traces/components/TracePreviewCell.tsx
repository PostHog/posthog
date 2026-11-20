import type { TracePreviewMissingReasonApi } from '../../../generated/api.schemas'
import type { TraceCellStatus } from '../types'
import { TraceCellValue } from './TraceCellValue'

const MISSING_REASON_LABELS: Record<TracePreviewMissingReasonApi, string> = {
    too_large: 'Too large to preview',
    timed_out: 'Preview timed out',
}

export interface TracePreviewCellProps {
    text: string | null
    missingReason: TracePreviewMissingReasonApi | null
    status: TraceCellStatus
}

function previewContent(text: string | null, missingReason: TracePreviewMissingReasonApi | null): JSX.Element | null {
    if (text !== null) {
        return (
            // The preview holds customer prompts and responses, so autocapture must not record it.
            <div title={text} className="ph-no-capture max-w-48 min-w-0 truncate">
                {text}
            </div>
        )
    }
    if (missingReason !== null) {
        return <span className="text-muted whitespace-nowrap">{MISSING_REASON_LABELS[missingReason]}</span>
    }
    return null
}

export function TracePreviewCell({ text, missingReason, status }: TracePreviewCellProps): JSX.Element {
    return (
        <TraceCellValue status={status} skeletonWidth="w-32">
            {previewContent(text, missingReason)}
        </TraceCellValue>
    )
}
