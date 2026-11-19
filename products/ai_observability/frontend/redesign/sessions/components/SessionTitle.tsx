import clsx from 'clsx'

import type { TracePreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'

export interface SessionTitleProps {
    title: TraceCellLoad<TracePreviewApi>
    className?: string
}

export function SessionTitle({ title, className }: SessionTitleProps): JSX.Element {
    const text = title.status === 'ready' ? title.value.input : null
    return (
        <TraceCellValue status={title.status} skeletonWidth="w-48">
            {/* The title is the customer's first prompt, so autocapture must not record it. */}
            <div title={text ?? undefined} className={clsx('ph-no-capture truncate', !text && 'text-muted', className)}>
                {text ?? 'Untitled session'}
            </div>
        </TraceCellValue>
    )
}
