import { useState } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover/Popover'

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { FeedbackTag } from './FeedbackTag'
import { MetricTag } from './MetricTag'

const INLINE_LIMIT = 3

interface AttachedFeedbackPillsProps {
    events: LLMTraceEvent[]
}

function renderTag(event: LLMTraceEvent): JSX.Element {
    return event.event === '$ai_feedback' ? (
        <FeedbackTag key={event.id} properties={event.properties} />
    ) : (
        <MetricTag key={event.id} properties={event.properties} />
    )
}

export function AttachedFeedbackPills({ events }: AttachedFeedbackPillsProps): JSX.Element | null {
    const [overflowOpen, setOverflowOpen] = useState(false)

    if (events.length === 0) {
        return null
    }

    const inline = events.slice(0, INLINE_LIMIT)
    const overflow = events.slice(INLINE_LIMIT)

    return (
        <>
            {inline.map(renderTag)}
            {overflow.length > 0 && (
                <Popover
                    visible={overflowOpen}
                    onClickOutside={() => setOverflowOpen(false)}
                    overlay={<div className="flex flex-col gap-1 p-1">{overflow.map(renderTag)}</div>}
                    placement="bottom"
                >
                    <LemonTag
                        className="bg-surface-primary cursor-pointer"
                        onClick={() => setOverflowOpen(!overflowOpen)}
                    >
                        {`+${overflow.length} more`}
                    </LemonTag>
                </Popover>
            )}
        </>
    )
}
