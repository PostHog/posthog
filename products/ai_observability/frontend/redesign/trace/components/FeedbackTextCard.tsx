import { cn } from 'lib/utils/css-classes'

import type { TraceFeedbackTextApi } from '../../../generated/api.schemas'
import { FeedbackStepContext } from '../types'
import { FeedbackStepLink } from './FeedbackStepLink'
import { scrollIntoNearest } from './scrollIntoNearest'
import { ShortTimestamp } from './ShortTimestamp'

export interface FeedbackTextCardProps {
    item: TraceFeedbackTextApi
    steps: FeedbackStepContext
    onSelectStep: (nodeId: string) => void
    /** Brings the card into view when it mounts. */
    isScrollTarget: boolean
}

export function FeedbackTextCard({ item, steps, onSelectStep, isScrollTarget }: FeedbackTextCardProps): JSX.Element {
    return (
        <li
            ref={isScrollTarget ? scrollIntoNearest : undefined}
            className={cn(
                'flex flex-col gap-1 px-3 py-2',
                item.nodeId === steps.focusNodeId && 'bg-accent-highlight-secondary'
            )}
        >
            <div className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1 text-xs text-secondary">
                <FeedbackStepLink nodeId={item.nodeId} steps={steps} onSelectStep={onSelectStep} />
                <ShortTimestamp time={item.timestamp} />
            </div>
            <p className="m-0 whitespace-pre-wrap break-words text-sm">{item.text}</p>
        </li>
    )
}
