import { IconInfo } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { ModelViewSummaryProps } from './ModelViewSummary'
import { QuillModelDownstreamSummary } from './QuillModelDownstreamSummary'
import { QuillModelFacts } from './QuillModelFacts'
import { QuillModelSummaryCard } from './QuillModelSummaryCard'

export function QuillModelViewSummary({ downstreamCount, lineageUrl, metadata }: ModelViewSummaryProps): JSX.Element {
    return (
        <QuillModelSummaryCard metadata={metadata} dataAttr="node-detail-view-summary">
            <div className="flex items-center gap-1">
                <Text size="xs" weight="semibold" render={<span />}>
                    Runs on demand
                </Text>
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About on-demand views" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent>Materialize to store results and refresh them on a schedule.</TooltipContent>
                </Tooltip>
            </div>
            <QuillModelFacts>
                <QuillModelDownstreamSummary downstreamCount={downstreamCount} lineageUrl={lineageUrl} />
            </QuillModelFacts>
        </QuillModelSummaryCard>
    )
}
