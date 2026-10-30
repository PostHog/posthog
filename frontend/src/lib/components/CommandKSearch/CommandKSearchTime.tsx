import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { formatRelativeTimeShort } from 'lib/components/Search/utils'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

export function CommandKSearchTime({
    time,
    prefix,
    tooltipLabel,
}: {
    time: string
    prefix?: string
    tooltipLabel: string
}): JSX.Element {
    const relative = formatRelativeTimeShort(time)
    return (
        <Tooltip>
            <TooltipTrigger
                render={<span className="shrink-0 whitespace-nowrap" translate="no" />}
                data-attr="command-k-row-time"
            >
                {prefix ? `${prefix} ${relative}` : relative}
            </TooltipTrigger>
            <TooltipContent>
                {`${tooltipLabel} ${humanFriendlyDetailedTime(time, 'MMMM D, YYYY', 'h:mm A', { timestampStyle: 'absolute' })}`}
            </TooltipContent>
        </Tooltip>
    )
}
