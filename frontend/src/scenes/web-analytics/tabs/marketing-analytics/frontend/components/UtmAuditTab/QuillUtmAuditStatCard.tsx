import { Card, CardContent, Skeleton, Text, cn } from '@posthog/quill'

export function QuillUtmAuditStatCard({
    label,
    value,
    loading,
    alert,
}: {
    label: string
    value: number
    loading?: boolean
    alert?: boolean
}): JSX.Element {
    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-1">
                <Text size="xs" variant="muted" render={<div />}>
                    {label}
                </Text>
                {loading ? (
                    <Skeleton className="h-7 w-12" />
                ) : (
                    <Text
                        size="lg"
                        weight="semibold"
                        className={cn('tabular-nums', alert && 'text-warning-foreground')}
                        render={<div />}
                    >
                        {value.toLocaleString()}
                    </Text>
                )}
            </CardContent>
        </Card>
    )
}
