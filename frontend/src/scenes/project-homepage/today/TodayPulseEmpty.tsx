import { IconPin, IconTrends } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle, IconStack, IconStackItem } from '@posthog/quill'

export function TodayPulseEmpty(): JSX.Element {
    return (
        <Empty className="TodayEmpty" data-attr="today-pulse-empty">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-product-analytics-light)">
                        <IconTrends />
                    </IconStackItem>
                    <IconStackItem>
                        <IconPin />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>No key numbers yet</EmptyTitle>
                <EmptyDescription>
                    Select Edit to pin a trend insight. PostHog also adds the trend insights your team opens most.
                </EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}
