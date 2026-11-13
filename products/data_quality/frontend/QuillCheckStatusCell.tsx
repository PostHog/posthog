import { Badge, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { CHECK_STATUS_BADGE_VARIANTS } from './checkBadgeVariants'
import { failingForLabel } from './checksConstants'
import type { DataQualityCheckApi } from './generated/api.schemas'

export function QuillCheckStatusCell({
    check,
}: {
    check: Pick<DataQualityCheckApi, 'last_status' | 'last_succeeded_at' | 'failing_since'>
}): JSX.Element {
    const failingFor = failingForLabel(check)
    if (!check.last_status) {
        return <Badge>Not run yet</Badge>
    }
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant={CHECK_STATUS_BADGE_VARIANTS[check.last_status] ?? 'default'}>{check.last_status}</Badge>
            {failingFor &&
                (check.last_succeeded_at ? (
                    <Tooltip>
                        <TooltipTrigger
                            render={<Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />} />}
                        >
                            {failingFor}
                        </TooltipTrigger>
                        <TooltipContent>{`Last passed ${dayjs(check.last_succeeded_at).fromNow()}`}</TooltipContent>
                    </Tooltip>
                ) : (
                    <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
                        {failingFor}
                    </Text>
                ))}
        </div>
    )
}
