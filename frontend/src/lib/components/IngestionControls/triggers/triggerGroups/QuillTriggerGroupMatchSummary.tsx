import { Badge, Text } from '@posthog/quill'

export function QuillTriggerGroupMatchSummary({
    hasConditions,
    matchType,
}: {
    hasConditions: boolean
    matchType: 'any' | 'all'
}): JSX.Element {
    return (
        <Text size="xs" render={<p className="m-0 flex flex-wrap items-center gap-1" />}>
            {hasConditions ? (
                <>
                    <span>
                        Match <b>sessions</b> against
                    </span>
                    <Badge variant="success" className="uppercase">
                        {matchType}
                    </Badge>
                    <span>criteria</span>
                </>
            ) : (
                <>
                    <span>Trigger group will match</span>
                    <Badge variant="success">all sessions</Badge>
                </>
            )}
        </Text>
    )
}
