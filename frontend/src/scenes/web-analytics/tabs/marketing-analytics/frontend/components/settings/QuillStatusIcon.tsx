import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SourceStatus } from '../../logic/marketingAnalyticsLogic'
import { getStatusDisplay } from './StatusIcon'

const BADGE_VARIANT = {
    success: 'success',
    danger: 'destructive',
    primary: 'info',
} as const

export function QuillStatusIcon({ status, message }: { status: SourceStatus; message: string }): JSX.Element {
    const { tagType, icon } = getStatusDisplay(status)

    return (
        <Tooltip>
            <TooltipTrigger render={<span tabIndex={0} className="inline-flex items-center justify-center" />}>
                {icon && <span className="text-lg">{icon}</span>}
                {tagType && <Badge variant={BADGE_VARIANT[tagType]}>{status}</Badge>}
                {/* Screen readers don't announce the tooltip, so the trigger carries its message too. */}
                <span className="sr-only">{tagType ? message : `${status}: ${message}`}</span>
            </TooltipTrigger>
            <TooltipContent>{message}</TooltipContent>
        </Tooltip>
    )
}
