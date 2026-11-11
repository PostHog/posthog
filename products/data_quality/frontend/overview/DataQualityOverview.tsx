import { BindLogic, useActions, useValues } from 'kea'

import { IconChevronRight, IconGear } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { CheckEditorModal } from '../CheckEditorModal'
import { HEALTH_LABELS, HEALTH_TAG_TYPES, SUBJECT_TYPE_TAGS } from '../checksConstants'
import { dataQualityCheckEditorLogic } from '../dataQualityCheckEditorLogic'
import { DataQualityEmptyState } from './DataQualityEmptyState'
import {
    NEW_CHECK_ACTION_ID,
    OverviewStatusFilter,
    SubjectGroup,
    dataQualityOverviewLogic,
    subjectDisclosureId,
} from './dataQualityOverviewLogic'
import { overviewCheckEditorProps } from './overviewCheckEditorProps'
import { RunAllBanners } from './RunAllBanners'
import { SubjectChecksPanel } from './SubjectChecksPanel'
import { SubjectRunBanners } from './SubjectRunBanners'

const STATUS_FILTERS: { value: OverviewStatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'failing', label: 'Failing' },
    { value: 'never_run', label: 'Not run yet' },
]

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
        overviewSummary,
        lastActionCheckId,
    } = useValues(dataQualityOverviewLogic)
    const { setFilters, runChecks, loadOverview, setLastActionCheck } = useActions(dataQualityOverviewLogic)

    const editorProps = overviewCheckEditorProps({ lastActionCheckId, loadOverview, runChecks })
    const { openEditor } = useActions(dataQualityCheckEditorLogic(editorProps))

    const addCheck = (): void => {
        setLastActionCheck(null)
        openEditor(null, null)
    }

    const runningAll = (startingRun || isRunning) && runTarget?.kind === 'all'
    const anyRunActive = startingRun || isRunning
    const settingsButton = (
        <LemonButton
            type="tertiary"
            size="small"
            icon={<IconGear />}
            to={urls.settings('environment-data-quality')}
            tooltip="Data quality settings"
            aria-label="Data quality settings"
            data-attr="data-quality-overview-settings"
        />
    )
    const newCheckButton = (
        <LemonButton
            id={NEW_CHECK_ACTION_ID}
            type="primary"
            size="small"
            onClick={addCheck}
            data-attr="data-quality-overview-new-check"
        >
            New check
        </LemonButton>
    )

    if (!snapshotLoaded && overviewLoading) {
        return (
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSkeleton className="h-8 w-64 max-w-full" />
                    <LemonSkeleton className="h-8 w-48" />
                </div>
                <LemonSkeleton.Row repeat={3} fade />
            </div>
        )
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
                {checks.length === 0 ? (
                    <div className="flex justify-end gap-2">
                        {settingsButton}
                        {newCheckButton}
                    </div>
                ) : (
                    <div className="flex flex-wrap items-center gap-2">
                        <div className="flex flex-wrap items-center gap-2 grow basis-full @2xl/main-content:basis-0">
                            <LemonInput
                                type="search"
                                size="small"
                                placeholder="Search checks"
                                value={filters.search}
                                onChange={(search) => setFilters({ search })}
                                className="flex-1 min-w-40 max-w-64"
                            />
                            <LemonSegmentedButton
                                size="small"
                                value={filters.status}
                                onChange={(status) => setFilters({ status })}
                                options={STATUS_FILTERS}
                            />
                        </div>
                        <div className="flex flex-wrap items-center gap-2 ml-auto">
                            {settingsButton}
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => runChecks({ kind: 'all' })}
                                loading={runningAll}
                                disabledReason={anyRunActive && !runningAll ? 'Checks are already running' : undefined}
                                data-attr="data-quality-overview-run-all"
                            >
                                Run all checks
                            </LemonButton>
                            {newCheckButton}
                        </div>
                    </div>
                )}

                {overviewSummary && <p className="mb-0 text-secondary">{overviewSummary}</p>}

                <RunAllBanners />

                {checks.length === 0 ? (
                    <DataQualityEmptyState onAddCheck={addCheck} />
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

function SubjectSection({ group }: { group: SubjectGroup }): JSX.Element {
    const { expandedSubjectKeys, startingRun, isRunning, runningSubjectKey } = useValues(dataQualityOverviewLogic)
    const { toggleSubjectExpanded, runChecks } = useActions(dataQualityOverviewLogic)

    const subjectType = SUBJECT_TYPE_TAGS[group.subjectType]
    const expanded = expandedSubjectKeys.includes(group.subjectKey)
    const regionId = `data-quality-subject-checks-${group.subjectKey}`
    const running = runningSubjectKey === group.subjectKey
    const anyRunActive = startingRun || isRunning

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
                            className="font-semibold truncate max-w-full"
                            tooltip={`Open ${group.subjectName} in a new tab`}
                        >
                            {group.subjectName}
                        </Link>
                    ) : (
                        <span className="font-semibold truncate max-w-full">{group.subjectName}</span>
                    )}
                    <LemonTag type={HEALTH_TAG_TYPES[group.health] ?? 'default'}>
                        {HEALTH_LABELS[group.health] ?? group.health}
                    </LemonTag>
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

            <SubjectRunBanners group={group} />

            {/* Mounted only while open: a collapsed subject rendering its rows would put every
                check's controls in the tab order of a panel nobody can see. */}
            {expanded && (
                <div id={regionId} className="overflow-x-auto">
                    <SubjectChecksPanel group={group} />
                </div>
            )}
        </div>
    )
}
