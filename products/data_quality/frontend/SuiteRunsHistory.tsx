import { useActions, useValues } from 'kea'

import { LemonCollapse, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { CheckRunsTable } from './CheckRunsTable'
import { SUITE_RUN_STATUS_TAG_TYPES } from './checksConstants'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import type { DataQualitySuiteRunApi } from './generated/api.schemas'

export function SuiteRunsHistory(props: DataQualityChecksLogicProps): JSX.Element {
    const logic = dataQualityChecksLogic(props)
    const { suiteRuns, suiteRunsLoading, suiteRunCheckRunsBySuiteRunId, pendingCheckActions } = useValues(logic)
    const { loadSuiteRuns, loadSuiteRunCheckRuns } = useActions(logic)

    return (
        <LemonCollapse
            onChange={(key) => key && loadSuiteRuns()}
            panels={[
                {
                    key: 'runs',
                    header: 'Run history',
                    content: (
                        <LemonTable
                            size="small"
                            dataSource={suiteRuns}
                            rowKey="id"
                            loading={suiteRunsLoading}
                            nouns={['run', 'runs']}
                            emptyState="No runs yet"
                            expandable={{
                                onRowExpand: (suiteRun) => loadSuiteRunCheckRuns(suiteRun.id),
                                expandedRowRender: (suiteRun) => (
                                    <CheckRunsTable
                                        runs={suiteRunCheckRunsBySuiteRunId[suiteRun.id] ?? []}
                                        loading={pendingCheckActions.loadingSuiteRunRuns[suiteRun.id]}
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
                                    render: (_, suiteRun) =>
                                        suiteRun.started_at ? <TZLabel time={suiteRun.started_at} /> : '-',
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
                    ),
                },
            ]}
        />
    )
}

function suiteRunDuration(suiteRun: DataQualitySuiteRunApi): string {
    if (!suiteRun.started_at || !suiteRun.finished_at) {
        return '-'
    }
    const seconds = (new Date(suiteRun.finished_at).getTime() - new Date(suiteRun.started_at).getTime()) / 1000
    return humanFriendlyDuration(seconds, { maxUnits: 2 })
}
