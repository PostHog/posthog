import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { CheckRunsTable } from './CheckRunsTable'
import { SUITE_RUN_STATUS_TAG_TYPES } from './checksConstants'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import type { DataQualitySuiteRunApi } from './generated/api.schemas'

export function SuiteRunsHistory(props: DataQualityChecksLogicProps): JSX.Element {
    const logic = dataQualityChecksLogic(props)
    const { suiteRuns, suiteRunsLoading, suiteRunsError, suiteRunCheckRunsBySuiteRunId, pendingCheckActions } =
        useValues(logic)
    const { loadSuiteRuns, loadSuiteRunCheckRuns } = useActions(logic)

    return (
        <section className="border-t pt-6 mt-4 flex flex-col gap-3" aria-label="Check run history">
            <div className="flex items-center justify-between gap-2">
                <div>
                    <h3 className="mb-1">Check run history</h3>
                    <p className="text-secondary mb-0 text-sm">
                        Results from checks run together. Expand a run to see each check's result.
                    </p>
                </div>
                <LemonButton
                    icon={<IconRefresh />}
                    size="small"
                    loading={suiteRunsLoading}
                    onClick={loadSuiteRuns}
                    tooltip="Refresh check run history"
                    aria-label="Refresh check run history"
                />
            </div>
            <LemonTable
                size="small"
                dataSource={suiteRuns}
                rowKey="id"
                loading={suiteRunsLoading}
                nouns={['run', 'runs']}
                emptyState={
                    suiteRunsError
                        ? "Couldn't load the run history. Refresh to try again."
                        : 'No check runs yet. Run all checks to see results here.'
                }
                expandable={{
                    onRowExpand: (suiteRun) => loadSuiteRunCheckRuns(suiteRun.id),
                    expandedRowRender: (suiteRun) => (
                        <CheckRunsTable
                            subjectType={props.subjectType}
                            runs={suiteRunCheckRunsBySuiteRunId[suiteRun.id] ?? []}
                            loading={pendingCheckActions.loadingSuiteRunRuns[suiteRun.id]}
                            showCheck
                        />
                    ),
                }}
                columns={[
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, suiteRun) => (
                            <LemonTag type={SUITE_RUN_STATUS_TAG_TYPES[suiteRun.status] ?? 'default'}>
                                {suiteRun.status === 'empty' ? 'No checks matched' : suiteRun.status}
                            </LemonTag>
                        ),
                    },
                    { title: 'Trigger', key: 'trigger', render: (_, suiteRun) => suiteRun.trigger },
                    {
                        title: 'Started',
                        key: 'started_at',
                        render: (_, suiteRun) => (suiteRun.started_at ? <TZLabel time={suiteRun.started_at} /> : '-'),
                    },
                    {
                        title: 'Duration',
                        key: 'duration',
                        render: (_, suiteRun) => suiteRunDuration(suiteRun),
                    },
                    {
                        title: 'Outcome',
                        key: 'outcome',
                        render: (_, suiteRun) =>
                            `${suiteRun.checks_passed} passed, ${suiteRun.checks_failed} failed, ${suiteRun.checks_errored} errored, ${suiteRun.checks_skipped} skipped`,
                    },
                ]}
            />
        </section>
    )
}

function suiteRunDuration(suiteRun: DataQualitySuiteRunApi): string {
    if (!suiteRun.started_at || !suiteRun.finished_at) {
        return '-'
    }
    const seconds = (new Date(suiteRun.finished_at).getTime() - new Date(suiteRun.started_at).getTime()) / 1000
    return humanFriendlyDuration(seconds, { maxUnits: 2 })
}
