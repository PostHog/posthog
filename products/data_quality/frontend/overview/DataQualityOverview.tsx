import { BindLogic, useActions, useValues } from 'kea'

import { IconChevronRight, IconEllipsis } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonMenu,
    LemonSegmentedButton,
    LemonTable,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { CheckEditorModal } from '../CheckEditorModal'
import { CheckRunsTable } from '../CheckRunsTable'
import { HEALTH_TAG_TYPES, SUBJECT_TYPE_TAGS, checkDisplayName, checkTypeLabel } from '../checksConstants'
import { CheckStatusCell } from '../CheckStatusCell'
import { DataQualityCheckEditorLogicProps, dataQualityCheckEditorLogic } from '../dataQualityCheckEditorLogic'
import type { DataQualityOverviewCheckApi } from '../generated/api.schemas'
import {
    BROWSE_ACTION_ID,
    OverviewStatusFilter,
    SubjectGroup,
    dataQualityOverviewLogic,
    focusCandidatesAfterDelete,
    rowActionsId,
    subjectDisclosureId,
    subjectKeyOf,
} from './dataQualityOverviewLogic'

const STATUS_FILTERS: { value: OverviewStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'failing', label: 'Failing' },
    { value: 'never_run', label: 'Not run yet' },
]

function focusFirstAvailable(elementIds: string[]): void {
    // Runs after the removed row has left the DOM, so the first id that still resolves wins.
    window.requestAnimationFrame(() => {
        for (const elementId of elementIds) {
            const element = document.getElementById(elementId)
            if (element) {
                element.focus()
                return
            }
        }
    })
}

export function DataQualityOverview(): JSX.Element {
    const {
        checks,
        subjectGroups,
        overviewLoading,
        snapshotLoaded,
        overviewError,
        filters,
        filtersActive,
        startingRun,
        isRunning,
        runTarget,
        pollTimedOut,
        runError,
        overviewSummary,
        lastActionCheckId,
    } = useValues(dataQualityOverviewLogic)
    const { setFilters, runChecks, loadOverview } = useActions(dataQualityOverviewLogic)

    const editorProps: DataQualityCheckEditorLogicProps = {
        surface: 'data-quality-overview',
        onSaved: () => loadOverview(),
        onRunNow: (check) =>
            runChecks({ kind: 'subject', subjectKey: subjectKeyOf(check.subject_type, check.subject_uuid) }, [
                check.id,
            ]),
        onClosed: () => {
            if (lastActionCheckId) {
                focusFirstAvailable([rowActionsId(lastActionCheckId)])
            }
        },
    }

    const runningAll = (startingRun || isRunning) && runTarget?.kind === 'all'
    const anyRunActive = startingRun || isRunning

    if (!snapshotLoaded && overviewLoading) {
        return <LemonTable dataSource={[]} loading columns={[{ title: 'Check', key: 'name' }]} />
    }

    if (!snapshotLoaded && overviewError) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadOverview }}>
                Couldn't load data quality checks.
            </LemonBanner>
        )
    }

    return (
        <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
            <div className="flex flex-col gap-3">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                    <div className="flex flex-col md:flex-row md:items-center gap-2 w-full md:w-auto">
                        <LemonInput
                            type="search"
                            placeholder="Search checks"
                            value={filters.search}
                            onChange={(search) => setFilters({ search })}
                            className="w-full md:w-64"
                        />
                        <LemonSegmentedButton
                            size="small"
                            value={filters.status}
                            onChange={(status) => setFilters({ status })}
                            options={STATUS_FILTERS}
                            className="w-full md:w-auto"
                        />
                    </div>
                    <LemonButton
                        type="primary"
                        onClick={() => runChecks({ kind: 'all' })}
                        loading={runningAll}
                        disabledReason={
                            checks.length === 0
                                ? 'There are no checks to run'
                                : anyRunActive && !runningAll
                                  ? 'Checks are already running'
                                  : undefined
                        }
                        data-attr="data-quality-overview-run-all"
                    >
                        Run all checks
                    </LemonButton>
                </div>

                {overviewSummary && <p className="mb-0 text-secondary">{overviewSummary}</p>}

                {overviewError && snapshotLoaded && (
                    <LemonBanner type="warning" action={{ children: 'Retry', onClick: loadOverview }}>
                        Couldn't refresh checks. Showing the latest available results.
                    </LemonBanner>
                )}
                {runningAll && (
                    <LemonBanner type="info" icon={<Spinner />}>
                        Running checks...
                    </LemonBanner>
                )}
                {pollTimedOut && runTarget?.kind === 'all' && (
                    <LemonBanner type="warning" action={{ children: 'Refresh', onClick: loadOverview }}>
                        Checks are still running. Check back in a few minutes.
                    </LemonBanner>
                )}
                {runError && runTarget?.kind === 'all' && (
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => runChecks({ kind: 'all' }) }}>
                        {runError}
                    </LemonBanner>
                )}

                {checks.length === 0 ? (
                    <NoChecksYet />
                ) : subjectGroups.length === 0 ? (
                    <div className="flex items-center gap-2">
                        <span className="text-secondary">No checks match these filters.</span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => setFilters({ search: '', status: 'all' })}
                            disabledReason={filtersActive ? undefined : 'No filters are set'}
                        >
                            Clear filters
                        </LemonButton>
                    </div>
                ) : (
                    subjectGroups.map((group) => <SubjectSection key={group.subjectKey} group={group} />)
                )}

                <CheckEditorModal />
            </div>
        </BindLogic>
    )
}

function NoChecksYet(): JSX.Element {
    return (
        <div className="border rounded p-4 flex flex-col items-start gap-2">
            <h4 className="mb-0">No checks yet</h4>
            <p className="mb-0 text-secondary">Add a check from a table or view to monitor data quality here.</p>
            <LemonButton
                id={BROWSE_ACTION_ID}
                type="primary"
                size="small"
                to={urls.database()}
                data-attr="data-quality-overview-browse"
            >
                Browse tables and views
            </LemonButton>
        </div>
    )
}

function SubjectSection({ group }: { group: SubjectGroup }): JSX.Element {
    const { expandedSubjectKeys, startingRun, isRunning, runningSubjectKey, runTarget, runError, pollTimedOut } =
        useValues(dataQualityOverviewLogic)
    const { toggleSubjectExpanded, runChecks, loadOverview } = useActions(dataQualityOverviewLogic)

    const subjectType = SUBJECT_TYPE_TAGS[group.subjectType]
    const expanded = expandedSubjectKeys.includes(group.subjectKey)
    const regionId = `data-quality-subject-checks-${group.subjectKey}`
    const running = runningSubjectKey === group.subjectKey
    const anyRunActive = startingRun || isRunning
    const scopedToThisSubject = runTarget?.kind === 'subject' && runTarget.subjectKey === group.subjectKey

    return (
        <div className="border rounded">
            {/* Separate controls rather than one collapse header: a link and a button inside a
                header button are not reachable by keyboard in the order they are read. */}
            <div className="flex flex-wrap items-center gap-2 p-2">
                <LemonButton
                    id={subjectDisclosureId(group.subjectKey)}
                    size="small"
                    icon={<IconChevronRight className={expanded ? 'rotate-90' : undefined} />}
                    onClick={() => toggleSubjectExpanded(group.subjectKey)}
                    aria-expanded={expanded}
                    aria-controls={regionId}
                    aria-label={`${expanded ? 'Collapse' : 'Expand'} checks for ${group.subjectName}`}
                    data-attr="data-quality-subject-disclosure"
                />
                <div className="flex flex-wrap items-center gap-2 flex-1">
                    {group.detailUrl ? (
                        // A new tab, and the external-link icon that comes with it: this page is a
                        // watchlist people work down, so opening a subject must not lose their place.
                        <Link
                            to={group.detailUrl}
                            target="_blank"
                            className="font-semibold"
                            tooltip={`Open ${group.subjectName} in a new tab`}
                        >
                            {group.subjectName}
                        </Link>
                    ) : (
                        <span className="font-semibold">{group.subjectName}</span>
                    )}
                    <LemonTag type={HEALTH_TAG_TYPES[group.health] ?? 'default'}>{group.health}</LemonTag>
                    {subjectType && <LemonTag type={subjectType.type}>{subjectType.label}</LemonTag>}
                    <span className="text-secondary text-sm">
                        {group.checksFailing > 0
                            ? `${group.checksFailing} of ${group.checksTotal} failing`
                            : `${group.checks.length} ${group.checks.length === 1 ? 'check' : 'checks'}`}
                    </span>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={running}
                    disabledReason={anyRunActive && !running ? 'Checks are already running' : undefined}
                    onClick={() =>
                        runChecks(
                            { kind: 'subject', subjectKey: group.subjectKey },
                            group.checks.map((check) => check.id)
                        )
                    }
                    data-attr="data-quality-overview-run-subject"
                >
                    Run these checks
                </LemonButton>
            </div>

            {scopedToThisSubject && running && (
                <p className="px-2 pb-2 mb-0 text-secondary text-sm">Running checks...</p>
            )}
            {scopedToThisSubject && pollTimedOut && (
                <div className="px-2 pb-2">
                    <LemonBanner type="warning" action={{ children: 'Refresh', onClick: loadOverview }}>
                        Checks are still running. Check back in a few minutes.
                    </LemonBanner>
                </div>
            )}
            {scopedToThisSubject && runError && (
                <div className="px-2 pb-2">
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: () =>
                                runChecks(
                                    { kind: 'subject', subjectKey: group.subjectKey },
                                    group.checks.map((check) => check.id)
                                ),
                        }}
                    >
                        {runError}
                    </LemonBanner>
                </div>
            )}

            {/* Mounted only while open: a collapsed subject rendering its rows would put every
                check's controls in the tab order of a panel nobody can see. */}
            {expanded && (
                <div id={regionId} className="overflow-x-auto">
                    <SubjectChecks group={group} />
                </div>
            )}
        </div>
    )
}

function SubjectChecks({ group }: { group: SubjectGroup }): JSX.Element {
    const { checkRunsByCheckId, runsLoadingByCheckId, deletingCheckIds, subjectGroups, startingRun, isRunning } =
        useValues(dataQualityOverviewLogic)
    const { loadCheckRuns, deleteCheck, setLastActionCheck, openFailingRows, runChecks } =
        useActions(dataQualityOverviewLogic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)

    const confirmDelete = (check: DataQualityOverviewCheckApi): void => {
        const fallbacks = focusCandidatesAfterDelete(subjectGroups, group.subjectKey, check.id)
        LemonDialog.open({
            title: 'Delete this check?',
            description: 'Past run history is kept.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => {
                    deleteCheck(check)
                    focusFirstAvailable(fallbacks)
                },
            },
            secondaryButton: {
                children: 'Cancel',
                onClick: () => focusFirstAvailable([rowActionsId(check.id)]),
            },
        })
    }

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
                { title: 'Check', key: 'name', render: (_, check) => checkDisplayName(check) },
                { title: 'Type', key: 'check_type', render: (_, check) => checkTypeLabel(check.check_type) },
                { title: 'Column', key: 'column_name', render: (_, check) => check.column_name || '-' },
                {
                    title: 'Last status',
                    key: 'last_status',
                    render: (_, check) => <CheckStatusCell check={check} />,
                },
                {
                    title: 'Last run',
                    key: 'last_run_at',
                    render: (_, check) => (check.last_run_at ? <TZLabel time={check.last_run_at} /> : '-'),
                },
                {
                    key: 'actions',
                    width: 0,
                    render: (_, check) => (
                        <LemonMenu
                            items={[
                                {
                                    // Reported into this subject's panel, since that is where its
                                    // result lands either way.
                                    label: 'Run now',
                                    onClick: () =>
                                        runChecks({ kind: 'subject', subjectKey: group.subjectKey }, [check.id]),
                                    disabledReason: startingRun || isRunning ? 'Checks are already running' : undefined,
                                },
                                {
                                    label: 'Edit',
                                    onClick: () => {
                                        setLastActionCheck(check.id)
                                        openEditor(check, {
                                            subjectType: check.subject_type,
                                            subjectId: check.subject_uuid ?? '',
                                        })
                                    },
                                },
                                {
                                    label: 'Open failing rows in SQL editor',
                                    tooltip: "The query behind this check's latest run",
                                    onClick: () => openFailingRows(check),
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => confirmDelete(check),
                                    disabledReason: deletingCheckIds[check.id]
                                        ? 'This check is being deleted'
                                        : undefined,
                                },
                            ]}
                        >
                            <LemonButton
                                id={rowActionsId(check.id)}
                                size="small"
                                icon={<IconEllipsis />}
                                data-attr="data-quality-overview-check-actions"
                                aria-label={`Actions for check ${checkDisplayName(check)}`}
                            />
                        </LemonMenu>
                    ),
                },
            ]}
        />
    )
}
