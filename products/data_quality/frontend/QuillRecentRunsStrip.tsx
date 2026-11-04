import { useActions, useValues } from 'kea'

import { Button, Dot, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { suiteRunDotVariant } from './checkBadgeVariants'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import type { DataQualitySuiteRunApi } from './generated/api.schemas'
import { suiteRunSummary } from './suiteRuns'

const RECENT_RUN_COUNT = 10

function triggerLabel(trigger: string): string {
    return trigger.replaceAll('_', ' ')
}

function RecentRunDot({ suiteRun }: { suiteRun: DataQualitySuiteRunApi }): JSX.Element {
    const summary = suiteRun.status === 'empty' ? 'No checks matched' : suiteRunSummary(suiteRun)
    const variant = suiteRunDotVariant(suiteRun)

    return (
        <Tooltip>
            <TooltipTrigger
                render={<span role="listitem" aria-label={`${triggerLabel(suiteRun.trigger)} run: ${summary}`} />}
            >
                <Dot variant={variant} pulse={variant === 'info'} />
            </TooltipTrigger>
            <TooltipContent>
                <div className="flex flex-col gap-0.5">
                    {suiteRun.started_at && <TZLabel time={suiteRun.started_at} />}
                    <span>{`Trigger: ${triggerLabel(suiteRun.trigger)}`}</span>
                    <span>{summary}</span>
                </div>
            </TooltipContent>
        </Tooltip>
    )
}

export function QuillRecentRunsStrip(props: DataQualityChecksLogicProps): JSX.Element | null {
    const logic = dataQualityChecksLogic(props)
    const { suiteRuns } = useValues(logic)
    const { openRunHistory } = useActions(logic)

    if (suiteRuns.length === 0) {
        return null
    }
    const latestRun = suiteRuns[0]
    const recentRuns = suiteRuns.slice(0, RECENT_RUN_COUNT).reverse()

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1" data-attr="data-quality-recent-runs">
            <div className="flex items-center gap-2">
                <Text size="xs" variant="muted" render={<span />}>
                    Recent runs
                </Text>
                <div className="flex items-center gap-0.5" role="list" aria-label="Recent runs, oldest first">
                    {recentRuns.map((suiteRun) => (
                        <RecentRunDot key={suiteRun.id} suiteRun={suiteRun} />
                    ))}
                </div>
            </div>
            {latestRun.started_at && (
                <Text size="xs" variant="muted" render={<span />}>
                    Last run <TZLabel time={latestRun.started_at} />
                </Text>
            )}
            <Button variant="link" size="inline" onClick={openRunHistory} data-attr="data-quality-view-run-history">
                View run history
            </Button>
        </div>
    )
}
