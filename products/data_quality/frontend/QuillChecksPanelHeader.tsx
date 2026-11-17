import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Badge, Button, Heading, Text } from '@posthog/quill'

import { HEALTH_BADGE_VARIANTS } from './checkBadgeVariants'
import { HEALTH_LABELS } from './checksConstants'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { QuillRecentRunsStrip } from './QuillRecentRunsStrip'

export interface QuillChecksPanelHeaderProps extends DataQualityChecksLogicProps {
    hideTitle?: boolean
    onAddCheck: () => void
    newCheckDisabledReason?: string
}

export function QuillChecksPanelHeader({
    hideTitle,
    onAddCheck,
    newCheckDisabledReason,
    ...logicProps
}: QuillChecksPanelHeaderProps): JSX.Element {
    const logic = dataQualityChecksLogic(logicProps)
    const { health, checksLoading, enabledChecksCount, isSuiteRunning, runAllInFlight } = useValues(logic)
    const { runAll } = useActions(logic)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <Heading size="base" render={<h3 className="m-0" />}>
                        {hideTitle ? 'Checks' : 'Data quality'}
                    </Heading>
                    {health && (
                        <Badge variant={HEALTH_BADGE_VARIANTS[health.health] ?? 'default'}>
                            {HEALTH_LABELS[health.health] ?? health.health}
                        </Badge>
                    )}
                    {health && health.checks_total > 0 && (
                        <Text size="xs" variant="muted" render={<span />}>
                            {`${health.checks_failing} of ${health.checks_total} failing`}
                        </Text>
                    )}
                    {health?.health === 'unknown' && (
                        <Text size="xs" variant="muted" render={<span />}>
                            Run checks to see health
                        </Text>
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Button
                        variant="outline"
                        onClick={runAll}
                        loading={runAllInFlight || isSuiteRunning}
                        disabledReason={
                            checksLoading
                                ? 'Loading checks'
                                : enabledChecksCount === 0
                                  ? 'No enabled checks to run'
                                  : undefined
                        }
                        data-attr="data-quality-run-all"
                    >
                        Run all checks
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onAddCheck}
                        disabledReason={newCheckDisabledReason}
                        data-attr="data-quality-new-check"
                    >
                        <IconPlus />
                        New check
                    </Button>
                </div>
            </div>
            <QuillRecentRunsStrip {...logicProps} />
        </div>
    )
}
