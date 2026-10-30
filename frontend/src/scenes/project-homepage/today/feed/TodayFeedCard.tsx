import { Button, Card, CardContent, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export function TodayFeedCard({
    title,
    description,
    actionLabel,
    to,
    onOpen,
    onEnroll,
    enrolled,
}: {
    title: string
    description: string
    actionLabel: string
    to: string
    onOpen: () => void
    onEnroll?: () => void
    enrolled: boolean
}): JSX.Element {
    return (
        <Card size="sm">
            <CardContent className="flex items-center justify-between gap-3">
                <span className="flex min-w-0 flex-col gap-0.5">
                    <Text size="sm" weight="semibold" className="truncate">
                        {title}
                    </Text>
                    {description && (
                        <Text size="xs" variant="muted" className="line-clamp-2">
                            {description}
                        </Text>
                    )}
                </span>
                {onEnroll ? (
                    <Button
                        variant={enrolled ? 'outline' : 'primary'}
                        onClick={onEnroll}
                        disabledReason={enrolled ? 'You turned this on' : undefined}
                        data-attr="today-feed-enroll"
                    >
                        {enrolled ? 'Turned on' : actionLabel}
                    </Button>
                ) : (
                    <Button
                        variant="outline"
                        render={<LinkPrimitive to={to} onClick={onOpen} />}
                        data-attr="today-feed-card-open"
                    >
                        {actionLabel}
                    </Button>
                )}
            </CardContent>
        </Card>
    )
}
