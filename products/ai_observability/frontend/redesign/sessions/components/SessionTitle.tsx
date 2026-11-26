import clsx from 'clsx'

import type { SessionPreviewApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'

export interface SessionTitleProps {
    title: TraceCellLoad<SessionPreviewApi>
    failedMessage?: string
    className?: string
}

export function SessionTitle({ title, failedMessage, className }: SessionTitleProps): JSX.Element {
    const text = title.status === 'ready' ? title.value.input : null
    return (
        <TraceCellValue status={title.status} skeletonWidth="w-48" failedMessage={failedMessage}>
            {/* The title is the customer's first prompt, so autocapture must not record it. */}
            <div title={text ?? undefined} className={clsx('ph-no-capture truncate', !text && 'text-muted', className)}>
                {text ?? 'Untitled session'}
            </div>
        </TraceCellValue>
    )
}
