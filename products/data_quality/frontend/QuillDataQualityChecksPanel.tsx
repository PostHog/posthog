import { BindLogic, useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Skeleton,
    Text,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { HEALTH_BADGE_VARIANTS } from './checkBadgeVariants'
import { HEALTH_LABELS } from './checksConstants'
import { DataQualityCheckEditorLogicProps, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { QuillCheckCallout } from './QuillCheckCallout'
import { QuillCheckEditorDialog } from './QuillCheckEditorDialog'
import { QuillChecksTable } from './QuillChecksTable'
import { QuillMetricChecksEmptyState } from './QuillMetricChecksEmptyState'
import { QuillSuiteRunsHistory } from './QuillSuiteRunsHistory'

export interface QuillDataQualityChecksPanelProps extends DataQualityChecksLogicProps {
    columns: DatabaseSchemaField[]
    dataLastSyncedAt?: string | null
    hideTitle?: boolean
    newCheckDisabledReason?: string
    notice?: ReactNode
    subjectName?: string
}

function NoChecksYet({ onAddCheck, disabledReason }: { onAddCheck: () => void; disabledReason?: string }): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>No checks yet</EmptyTitle>
                <EmptyDescription>
                    Checks verify this data automatically after each sync or materialization.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    variant="primary"
                    onClick={onAddCheck}
                    disabledReason={disabledReason}
                    data-attr="data-quality-first-check"
                >
                    Add your first check
                </Button>
            </EmptyContent>
        </Empty>
    )
}

export function QuillDataQualityChecksPanel({
    columns,
    subjectName,
    dataLastSyncedAt,
    hideTitle,
    newCheckDisabledReason,
    notice,
    ...logicProps
}: QuillDataQualityChecksPanelProps): JSX.Element | null {
    const logic = dataQualityChecksLogic(logicProps)
    const {
        health,
        checks,
        checksLoading,
        checksLoadError,
        checksLoaded,
        enabledChecksCount,
        isSuiteRunning,
        pollTimedOut,
        runAllInFlight,
        accessDenied,
    } = useValues(logic)
    const { runAll, loadChecks, loadHealth, upsertCheck, runCheck } = useActions(logic)

    const editorProps: DataQualityCheckEditorLogicProps = {
        surface: `subject:${logicProps.subjectType}:${logicProps.subjectId}`,
        onSaved: (check) => {
            upsertCheck(check)
            loadHealth()
        },
        onRunNow: (check) => runCheck(check.id),
    }
    const { openEditor, openEditorWithStarter } = useActions(dataQualityCheckEditorLogic(editorProps))
    const columnNames = columns.map((column) => column.name)
    const outputSchema = columns.map((column) => ({ name: column.name, type: column.type }))
    const addCheck = (): void => openEditor(null, logicProps, columnNames, outputSchema)
    const isMetric = logicProps.subjectType === 'metric'

    if (accessDenied) {
        return isMetric ? (
            <Text size="xs" variant="muted" className="m-0">
                You don't have access to the tests for this metric.
            </Text>
        ) : null
    }

    if (checksLoadError && !checksLoaded) {
        return (
            <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: loadChecks }}>
                Could not load the checks. Try again.
            </QuillCheckCallout>
        )
    }

    if (!checksLoaded) {
        return <Skeleton className="h-40 w-full" aria-busy="true" />
    }

    if (!checksLoading && checks.length === 0) {
        return (
            <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
                <div className="flex flex-col gap-3" data-attr="data-quality-checks-panel">
                    {notice}
                    {isMetric ? (
                        <QuillMetricChecksEmptyState
                            metricName={subjectName}
                            onStart={(starterKey) => openEditorWithStarter(logicProps, starterKey)}
                            disabledReason={newCheckDisabledReason}
                        />
                    ) : (
                        <NoChecksYet onAddCheck={addCheck} disabledReason={newCheckDisabledReason} />
                    )}
                    <QuillCheckEditorDialog />
                </div>
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
            <div className="flex flex-col gap-3" data-attr="data-quality-checks-panel">
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
                            onClick={addCheck}
                            disabledReason={newCheckDisabledReason}
                            data-attr="data-quality-new-check"
                        >
                            <IconPlus />
                            New check
                        </Button>
                    </div>
                </div>

                {notice}

                {dataLastSyncedAt && (
                    <Text size="xs" variant="muted" className="m-0">
                        Checks test the data from the last sync (synced <TZLabel time={dataLastSyncedAt} />
                        ). After you change this view, sync it to test the new query.
                    </Text>
                )}

                {checksLoadError && (
                    <QuillCheckCallout tone="warning" action={{ label: 'Retry', onClick: loadChecks }}>
                        Could not refresh the checks. Showing the latest available results.
                    </QuillCheckCallout>
                )}
                {isSuiteRunning && (
                    <QuillCheckCallout tone="info" busy>
                        Running checks...
                    </QuillCheckCallout>
                )}
                {pollTimedOut && (
                    <QuillCheckCallout
                        tone="warning"
                        action={{
                            label: 'Refresh',
                            onClick: () => {
                                loadChecks()
                                loadHealth()
                            },
                        }}
                    >
                        Checks are still running. Check back in a few minutes.
                    </QuillCheckCallout>
                )}

                <QuillChecksTable {...logicProps} columns={columnNames} outputSchema={outputSchema} />

                <QuillSuiteRunsHistory {...logicProps} />

                <QuillCheckEditorDialog />
            </div>
        </BindLogic>
    )
}
