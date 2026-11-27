import { useActions, useValues } from 'kea'

import { Button, Card, Heading, Text, cn } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SEVERITIES, SEVERITY_BAR_COLORS } from './ingestionWarningSeverity'
import { ingestionWarningsV2Logic } from './ingestionWarningsV2Logic'

/** The total, then one tile per severity that filters the list to it. */
export function QuillIngestionWarningsV2SummaryTiles(): JSX.Element {
    const { summaryStats, filters } = useValues(ingestionWarningsV2Logic)
    const { setFilters } = useActions(ingestionWarningsV2Logic)

    return (
        <div className="flex flex-wrap gap-2">
            <Card size="sm" className="min-w-30 gap-0.5 px-3 py-2">
                <Text size="xs" variant="muted" render={<span />}>
                    Warnings in window
                </Text>
                <Heading size="lg" render={<span />}>
                    {humanFriendlyNumber(summaryStats.totalCount)}
                </Heading>
            </Card>
            {SEVERITIES.map((severity) => {
                const count = summaryStats.bySeverity[severity]
                if (count === undefined && filters.severity !== severity) {
                    return null
                }
                const isActive = filters.severity === severity
                return (
                    <Button
                        key={severity}
                        variant="outline"
                        aria-pressed={isActive}
                        className={cn(
                            'h-auto min-w-30 flex-col items-start gap-0.5 px-3 py-2',
                            isActive && 'border-primary'
                        )}
                        onClick={() => setFilters({ severity: isActive ? null : severity })}
                    >
                        <Text size="xs" variant="muted" render={<span />} className="flex items-center gap-1.5">
                            <span className={cn('h-3 w-1 rounded-full', SEVERITY_BAR_COLORS[severity] ?? 'bg-muted')} />
                            {severity}
                        </Text>
                        <Heading size="lg" render={<span />}>
                            {humanFriendlyNumber(count ?? 0)}
                        </Heading>
                    </Button>
                )
            })}
        </div>
    )
}
