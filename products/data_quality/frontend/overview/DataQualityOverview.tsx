import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonSegmentedButton,
    LemonTable,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { CheckRunsTable } from '../CheckRunsTable'
import { CHECK_STATUS_TAG_TYPES, HEALTH_TAG_TYPES, SUBJECT_TYPE_TAGS, checkTypeLabel } from '../checksConstants'
import type { DataQualityCheckApi } from '../generated/api.schemas'
import { OverviewStatusFilter, SubjectGroup, dataQualityOverviewLogic } from './dataQualityOverviewLogic'

const STATUS_FILTERS: { value: OverviewStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'failing', label: 'Failing' },
    { value: 'never_run', label: 'Not run yet' },
]

export function DataQualityOverview(): JSX.Element {
    const {
        checks,
        subjectGroups,
        unhealthySubjectUuids,
        checksLoading,
        filters,
        startingRun,
        isRunning,
        pollTimedOut,
        failingCheckCount,
        failingSubjectCount,
    } = useValues(dataQualityOverviewLogic)
    const { setFilters, runChecks, refresh } = useActions(dataQualityOverviewLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <LemonInput
                        type="search"
                        placeholder="Search checks"
                        value={filters.search}
                        onChange={(search) => setFilters({ search })}
                    />
                    <LemonSegmentedButton
                        size="small"
                        value={filters.status}
                        onChange={(status) => setFilters({ status })}
                        options={STATUS_FILTERS}
                    />
                </div>
                <LemonButton
                    type="primary"
                    onClick={() => runChecks()}
                    loading={startingRun || isRunning}
                    disabledReason={checks.length === 0 ? 'There are no checks to run' : undefined}
                    data-attr="data-quality-overview-run-all"
                >
                    Run all checks
                </LemonButton>
            </div>

            {!checksLoading && checks.length > 0 && (
                <p className="mb-0 text-secondary">
                    {failingCheckCount === 0
                        ? `All ${checks.length} checks passed on their last run.`
                        : `${failingCheckCount} of ${checks.length} checks failing, across ${failingSubjectCount} tables and views.`}
                </p>
            )}

            {isRunning && (
                <LemonBanner type="info" icon={<Spinner />}>
                    Running checks...
                </LemonBanner>
            )}
            {pollTimedOut && (
                <LemonBanner type="warning" action={{ children: 'Refresh', onClick: refresh }}>
                    Checks are still running. Check back in a few minutes.
                </LemonBanner>
            )}

            {checksLoading ? (
                <LemonTable dataSource={[]} loading columns={[{ title: 'Check', key: 'name' }]} />
            ) : subjectGroups.length === 0 ? (
                <p className="mb-0 text-secondary">No checks match these filters.</p>
            ) : (
                <LemonCollapse
                    multiple
                    defaultActiveKeys={unhealthySubjectUuids}
                    panels={subjectGroups.map((group) => ({
                        key: group.subjectUuid,
                        header: <SubjectHeader group={group} />,
                        content: <SubjectChecks group={group} />,
                    }))}
                />
            )}
        </div>
    )
}

function SubjectHeader({ group }: { group: SubjectGroup }): JSX.Element {
    const { startingRun, isRunning } = useValues(dataQualityOverviewLogic)
    const { runChecks } = useActions(dataQualityOverviewLogic)
    const subjectType = SUBJECT_TYPE_TAGS[group.subjectType]

    return (
        <div className="flex items-center justify-between gap-2 w-full">
            <div className="flex items-center gap-2">
                <span className="font-semibold">{group.subjectName}</span>
                {subjectType && <LemonTag type={subjectType.type}>{subjectType.label}</LemonTag>}
                <LemonTag type={HEALTH_TAG_TYPES[group.health] ?? 'default'}>{group.health}</LemonTag>
                <span className="text-secondary text-sm">
                    {group.checksFailing > 0
                        ? `${group.checksFailing} of ${group.checks.length} failing`
                        : `${group.checks.length} ${group.checks.length === 1 ? 'check' : 'checks'}`}
                </span>
            </div>
            <LemonButton
                type="secondary"
                size="xsmall"
                loading={startingRun || isRunning}
                onClick={(event) => {
                    // The header is the collapse trigger, so the click must not also toggle the panel.
                    event.stopPropagation()
                    runChecks(group.checks.map((check) => check.id))
                }}
                data-attr="data-quality-overview-run-subject"
            >
                Run these checks
            </LemonButton>
        </div>
    )
}

function SubjectChecks({ group }: { group: SubjectGroup }): JSX.Element {
    const { checkRunsByCheckId, runsLoadingByCheckId } = useValues(dataQualityOverviewLogic)
    const { loadCheckRuns } = useActions(dataQualityOverviewLogic)

    return (
        <LemonTable
            size="small"
            dataSource={group.checks}
            rowKey="id"
            nouns={['check', 'checks']}
            expandable={{
                onRowExpand: (check) => loadCheckRuns(check),
                expandedRowRender: (check) => (
                    <div className="flex flex-col gap-2 py-2">
                        {check.description && <p className="mb-0 text-secondary">{check.description}</p>}
                        <CheckRunsTable
                            runs={checkRunsByCheckId[check.id] ?? []}
                            loading={runsLoadingByCheckId[check.id]}
                        />
                    </div>
                ),
            }}
            columns={[
                { title: 'Check', key: 'name', render: (_, check) => checkLabel(check) },
                { title: 'Type', key: 'check_type', render: (_, check) => checkTypeLabel(check.check_type) },
                { title: 'Column', key: 'column_name', render: (_, check) => check.column_name || '-' },
                {
                    title: 'Last status',
                    key: 'last_status',
                    render: (_, check) =>
                        check.last_status ? (
                            <LemonTag type={CHECK_STATUS_TAG_TYPES[check.last_status] ?? 'default'}>
                                {check.last_status}
                            </LemonTag>
                        ) : (
                            <LemonTag type="muted">Not run yet</LemonTag>
                        ),
                },
                {
                    title: 'Last run',
                    key: 'last_run_at',
                    render: (_, check) => (check.last_run_at ? <TZLabel time={check.last_run_at} /> : '-'),
                },
                {
                    key: 'open',
                    width: 0,
                    render: (_, check) =>
                        check.subject_type === 'view' && check.subject_uuid ? (
                            <Link to={urls.sqlEditor({ view_id: check.subject_uuid })}>Open</Link>
                        ) : null,
                },
            ]}
        />
    )
}

function checkLabel(check: DataQualityCheckApi): string {
    if (check.name) {
        return check.name
    }
    const label = checkTypeLabel(check.check_type)
    return check.column_name ? `${label} on ${check.column_name}` : label
}
