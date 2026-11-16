import { useActions, useValues } from 'kea'

import { Button, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { PulseSlotApi } from 'products/today/frontend/generated/api.schemas'

import { todayHighlightsLogic } from './todayHighlightsLogic'

export function pulsePlaceholderLabel(slot: PulseSlotApi): string {
    if (slot.status === 'pending') {
        return `${slot.name}: Loading`
    }
    return `${slot.name}: ${slot.status === 'error' ? 'Could not load' : 'No data'}`
}

export function TodayPulsePlaceholder({ slot }: { slot: PulseSlotApi }): JSX.Element {
    const { highlightsLoading, highlights, highlightsFailed } = useValues(todayHighlightsLogic)
    const { retryPulse } = useActions(todayHighlightsLogic)
    const loading = slot.status === 'pending'
    return (
        <>
            {slot.url ? (
                <LinkPrimitive to={slot.url} className="TodayPulse__name">
                    {slot.name}
                </LinkPrimitive>
            ) : (
                <span className="TodayPulse__name">{slot.name}</span>
            )}
            <span className="TodayPulse__row">
                {loading ? (
                    <Skeleton className="inline-block h-5 w-24" />
                ) : (
                    <Text size="sm" variant="muted">
                        {slot.status === 'error' ? 'Could not load' : 'No data'}
                    </Text>
                )}
            </span>
            <span className="TodayPulse__spark">
                {loading ? (
                    <Skeleton className="h-3 w-full" />
                ) : slot.status === 'error' ? (
                    <Button
                        size="xs"
                        variant="link-muted"
                        className="-ms-2"
                        disabled={highlightsLoading || (!highlightsFailed && highlights?.status === 'computing')}
                        onClick={retryPulse}
                    >
                        Retry
                    </Button>
                ) : null}
            </span>
        </>
    )
}
