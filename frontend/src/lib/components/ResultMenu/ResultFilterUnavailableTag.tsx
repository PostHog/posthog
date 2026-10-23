import { LemonTag, Tooltip } from '@posthog/lemon-ui'
import { Badge, Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function ResultFilterUnavailableTag({ reason }: { reason: string }): JSX.Element {
    const quill = useFeatureFlag('TODAY_RAIL_NAV')
    return quill ? (
        <QuillTooltip>
            <TooltipTrigger
                render={
                    <span tabIndex={0} className="inline-flex shrink-0 ml-1.5" data-attr="dashboard-cannot-filter" />
                }
            >
                <Badge>Can't filter</Badge>
            </TooltipTrigger>
            <TooltipContent className="max-w-72 whitespace-normal">{reason}</TooltipContent>
        </QuillTooltip>
    ) : (
        <Tooltip title={reason}>
            <span tabIndex={0} className="inline-flex shrink-0 ml-1.5" data-attr="dashboard-cannot-filter">
                <LemonTag type="default" size="small">
                    Can't filter
                </LemonTag>
            </span>
        </Tooltip>
    )
}
