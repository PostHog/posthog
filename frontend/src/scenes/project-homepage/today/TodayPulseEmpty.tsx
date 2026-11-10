import { IconPin, IconTrends } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { TodayPulseEditor } from './TodayPulseEditor'

export function TodayPulseEmpty({ canPin }: { canPin: boolean }): JSX.Element {
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
                    Pin the trend insights you check every day. PostHog also adds the ones your team opens most.
                </EmptyDescription>
            </EmptyHeader>
            {canPin ? (
                <EmptyContent>
                    <TodayPulseEditor
                        align="center"
                        trigger={
                            <Button size="sm" variant="outline" data-attr="today-pulse-empty-pin">
                                <IconPin />
                                Pin a number
                            </Button>
                        }
                    />
                </EmptyContent>
            ) : null}
        </Empty>
    )
}
