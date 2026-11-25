import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { TracePreviewMissingReasonApi } from '../../../generated/api.schemas'

export interface TurnSideMissingNoticeProps {
    side: 'input' | 'output'
    reason: TracePreviewMissingReasonApi
    /** Whether part of the side shows, so the notice covers only the rest. */
    partial: boolean
    onOpenTrace: () => void
}

const SUBJECTS: Record<TurnSideMissingNoticeProps['side'], string> = {
    input: "the user's message",
    output: 'the answer',
}

const PREDICATES: Record<TracePreviewMissingReasonApi, string> = {
    too_large: 'is too large to show here',
    timed_out: 'took too long to load',
}

function noticeText({ side, reason, partial }: Omit<TurnSideMissingNoticeProps, 'onOpenTrace'>): string {
    const subject = SUBJECTS[side]
    const lead = partial ? `Part of ${subject}` : subject.charAt(0).toUpperCase() + subject.slice(1)
    return `${lead} ${PREDICATES[reason]}.`
}

export function TurnSideMissingNotice({ side, reason, partial, onOpenTrace }: TurnSideMissingNoticeProps): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-wrap items-center gap-2 text-xs text-secondary',
                side === 'input' ? 'self-end' : 'self-start'
            )}
        >
            <span>{noticeText({ side, reason, partial })}</span>
            <LemonButton
                size="xsmall"
                type="tertiary"
                onClick={onOpenTrace}
                data-attr="trace-view-thread-open-missing-side"
            >
                Open trace
            </LemonButton>
        </div>
    )
}
