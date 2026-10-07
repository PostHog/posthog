import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonSwitch, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { pluralize } from 'lib/utils/strings'

import {
    AccessControlLevel,
    AccessControlResourceType,
    AnyPropertyFilter,
    DateMappingOption,
    UserBasicType,
} from '~/types'

import type {
    EvaluationBackfillApi,
    EvaluationBackfillConditionApi,
    EvaluationBackfillStatusEnumApi,
} from '../../generated/api.schemas'
import {
    backfillCoveredCount,
    backfillLateArrivalCount,
    backfillLiveCoveredCount,
    backfillRangeDateFormat,
    backfillSamplingLabel,
    backfillTotalCount,
} from '../backfillConditions'
import { evaluationBackfillsLogic } from '../evaluationBackfillsLogic'
import { EvaluationTriggers } from './EvaluationTriggers'

const BACKFILL_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    { key: 'Last 24 hours', values: ['-24h'] },
    { key: 'Last 7 days', values: ['-7d'] },
    { key: 'Last 14 days', values: ['-14d'] },
    { key: 'Last 30 days', values: ['-30d'] },
]

const BACKFILL_STATUS_TAG: Record<EvaluationBackfillStatusEnumApi, { label: string; type: LemonTagType }> = {
    running: { label: 'Running', type: 'primary' },
    completed: { label: 'Completed', type: 'success' },
    cancelled: { label: 'Cancelled', type: 'muted' },
    interrupted: { label: 'Interrupted', type: 'warning' },
}

const WINDOW_TIME_FORMAT = { formatDate: 'MMM D, YYYY', formatTime: 'HH:mm' }

function backfillLeftBehindLabel(backfill: EvaluationBackfillApi): string | null {
    // Null coverage means nothing counted the window, and a covered run is already told by the
    // full bar, so only a run that left work behind has something to say.
    if (!backfill.remaining_count) {
        return null
    }
    const one = backfill.remaining_count === 1
    return `${pluralize(backfill.remaining_count, backfill.target)} ${one ? "wasn't" : "weren't"} evaluated. Retry remaining to try ${one ? 'it' : 'them'} again.`
}

function backfillUnitPlural(backfill: EvaluationBackfillApi): string {
    return pluralize(2, backfill.target, undefined, false)
}

function ConditionSetScope({
    condition,
    unitPlural,
}: {
    condition: EvaluationBackfillConditionApi
    unitPlural: string
}): JSX.Element {
    // The generated type carries property filters as plain dicts, while the display components take
    // the filter union. The two agree at runtime, mirroring the cast in `toRequestConditions`.
    const filters = (condition.properties ?? []) as AnyPropertyFilter[]
    return filters.length > 0 ? (
        <PropertyFiltersDisplay filters={filters} compact />
    ) : (
        <span className="whitespace-nowrap">All {unitPlural}</span>
    )
}

interface EvaluationBackfillsTabProps {
    evaluationId: string
    userAccessLevel?: AccessControlLevel
    onConfigurationClick: () => void
}

export function EvaluationBackfillsTab({
    evaluationId,
    userAccessLevel,
    onConfigurationClick,
}: EvaluationBackfillsTabProps): JSX.Element {
    const logic = evaluationBackfillsLogic({ evaluationId })
    const {
        backfills,
        backfillsError,
        backfillsLoading,
        clampedWindow,
        conditions,
        creatingBackfill,
        evaluation,
        hasActiveBackfill,
        estimate,
        estimateError,
        estimateLoading,
        estimateSummary,
        expandedBackfillIds,
        rerunExisting,
        settleWait,
        startDisabledReason,
        transitioningIds,
        unit,
        windowDateFrom,
        windowDateTo,
    } = useValues(logic)
    const {
        setWindowRange,
        setConditions,
        setRerunExisting,
        createBackfill,
        cancelBackfill,
        retryBackfill,
        expandBackfill,
        collapseBackfill,
        loadBackfills,
        startClicked,
    } = useActions(logic)

    const confirmStart = (): void => {
        startClicked()
        LemonDialog.open({
            title: 'Start this backfill?',
            description: estimate ? (
                <>
                    {pluralize(estimate.total_units, estimate.unit)}
                    {clampedWindow ? ` between ${clampedWindow.start} and ${clampedWindow.end}` : ''} will be evaluated,
                    and each one is billed as an AI observability event. You can cancel a run while it is in progress,
                    but results it already saved will stay.
                </>
            ) : undefined,
            primaryButton: {
                children: 'Start backfill',
                onClick: createBackfill,
                'data-attr': 'llma-eval-backfill-start-confirm',
            },
            secondaryButton: { children: 'Cancel' },
            // The overlay aligns modals to the top by default, as in WebAnalyticsFilterPresets.
            overlayClassName: '!items-center',
        })
    }

    const unitPlural = pluralize(2, unit, undefined, false)

    const columns: LemonTableColumns<EvaluationBackfillApi> = [
        {
            title: 'Range',
            key: 'window',
            className: '@max-[32rem]/backfills:hidden',
            // `timestampStyle="absolute"` suppresses the Today/Yesterday substitution, so two rows
            // can be compared as exact instants. TZLabel's timezone popover still holds the time of day.
            render: (_, backfill) => {
                const formatDate = backfillRangeDateFormat(backfill.window_start, backfill.window_end, dayjs())
                return (
                    <div className="flex items-center gap-1 flex-wrap">
                        <TZLabel
                            time={backfill.window_start}
                            timestampStyle="absolute"
                            formatDate={formatDate}
                            formatTime=""
                        />
                        <span className="text-muted">–</span>
                        <TZLabel
                            time={backfill.window_end}
                            timestampStyle="absolute"
                            formatDate={formatDate}
                            formatTime=""
                        />
                    </div>
                )
            },
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, backfill) => {
                const statusTag = (
                    <LemonTag
                        type={
                            backfill.status === 'completed' && backfill.failed_count
                                ? 'warning'
                                : BACKFILL_STATUS_TAG[backfill.status].type
                        }
                    >
                        {backfill.status === 'completed' && backfill.failed_count
                            ? 'Completed with errors'
                            : BACKFILL_STATUS_TAG[backfill.status].label}
                    </LemonTag>
                )
                return (
                    <div className="flex items-center gap-1 flex-wrap">
                        {backfill.status === 'completed' && backfill.completed_count == null ? (
                            <Tooltip
                                title={`Each ${backfill.target} is evaluated on its own, so the last results can take a few minutes to appear in the Runs tab.`}
                            >
                                {statusTag}
                            </Tooltip>
                        ) : (
                            statusTag
                        )}
                        <span className="hidden w-full text-muted @max-[32rem]/backfills:block">
                            <TZLabel
                                time={backfill.window_start}
                                timestampStyle="absolute"
                                formatDate="MMM D"
                                formatTime=""
                            />
                            {' – '}
                            <TZLabel
                                time={backfill.window_end}
                                timestampStyle="absolute"
                                formatDate="MMM D"
                                formatTime=""
                            />
                        </span>
                    </div>
                )
            },
        },
        {
            title: 'Scope',
            key: 'conditions',
            className: '@max-[48rem]/backfills:hidden',
            render: (_, backfill) => {
                // The Scope cell shows one condition set and folds the rest behind a "+N more".
                const [first, ...rest] = backfill.conditions
                if (!first) {
                    return <span className="text-secondary">-</span>
                }
                const rowUnitPlural = backfillUnitPlural(backfill)
                return (
                    <div className="flex items-center gap-1 flex-wrap">
                        <ConditionSetScope condition={first} unitPlural={rowUnitPlural} />
                        {rest.length > 0 && (
                            <Tooltip
                                title={
                                    <div className="flex flex-col gap-1">
                                        {/* Frozen condition sets carry no id and never reorder. */}
                                        {rest.map((condition, index) => (
                                            <div key={index} className="flex items-center gap-1 flex-wrap">
                                                <ConditionSetScope condition={condition} unitPlural={rowUnitPlural} />
                                                {(condition.rollout_percentage ?? 100) < 100 && (
                                                    <span>{backfillSamplingLabel(condition)}</span>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                }
                            >
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    onClick={() => expandBackfill(backfill.id)}
                                    data-attr="llma-eval-backfill-more-conditions"
                                >
                                    +{rest.length} more
                                </LemonButton>
                            </Tooltip>
                        )}
                        {(first.rollout_percentage ?? 100) < 100 && (
                            <LemonTag type="muted" size="small">
                                {backfillSamplingLabel(first)}
                            </LemonTag>
                        )}
                        {backfill.rerun_existing && (
                            <LemonTag type="muted" size="small">
                                Includes {rowUnitPlural} with a result
                            </LemonTag>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Progress',
            key: 'progress',
            render: (_, backfill) => {
                const measured = backfill.status === 'completed' && backfill.remaining_count !== null
                const covered = backfillCoveredCount(backfill)
                const total = backfillTotalCount(backfill)
                return (
                    <Tooltip
                        title={
                            backfill.completed_count != null
                                ? `${backfill.completed_count.toLocaleString('en-US')} evaluated, ${backfill.evaluation_skipped_count.toLocaleString('en-US')} skipped, ${backfill.skipped_count.toLocaleString('en-US')} already handled, ${backfill.failed_count.toLocaleString('en-US')} failed.`
                                : measured
                                  ? `Estimated coverage when this run ended. This older backfill did not track execution outcomes.`
                                  : `How many ${backfillUnitPlural(backfill)} this backfill has started evaluating or skipped because the evaluation already had them. It does not track which of them have finished.`
                        }
                    >
                        <div className="min-w-24">
                            <span className="whitespace-nowrap" translate="no">
                                {covered.toLocaleString('en-US')} / {total.toLocaleString('en-US')}
                            </span>
                            {backfill.dispatched_count > 0 && (
                                <span className="text-muted whitespace-nowrap">
                                    {' '}
                                    ·{' '}
                                    {backfill.completed_count != null
                                        ? `${backfill.completed_count.toLocaleString('en-US')} evaluated`
                                        : `${backfill.dispatched_count.toLocaleString('en-US')} started`}
                                </span>
                            )}
                            <LemonProgress
                                className="mt-1"
                                percent={total > 0 ? (covered / total) * 100 : 0}
                                strokeColor={backfill.status === 'running' ? undefined : 'var(--border)'}
                            />
                        </div>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Created',
            key: 'created_at',
            className: '@max-[48rem]/backfills:hidden',
            render: (_, backfill) => <TZLabel time={backfill.created_at} />,
        },
        {
            title: 'Created by',
            key: 'created_by',
            className: '@max-[48rem]/backfills:hidden',
            render: (_, backfill) =>
                backfill.created_by ? (
                    <ProfilePicture user={backfill.created_by as UserBasicType} size="md" showName />
                ) : (
                    <span className="text-secondary">-</span>
                ),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, backfill) =>
                backfill.status === 'running' ? (
                    <More
                        data-attr="llma-eval-backfill-actions"
                        overlay={
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Evaluation}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={userAccessLevel}
                            >
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    onClick={() => cancelBackfill(backfill.id)}
                                    disabledReason={transitioningIds.includes(backfill.id) ? 'Cancelling…' : undefined}
                                    data-attr="llma-eval-backfill-cancel"
                                >
                                    Cancel
                                </LemonButton>
                            </AccessControlAction>
                        }
                    />
                ) : backfill.status !== 'completed' || !!backfill.failed_count || !!backfill.remaining_count ? (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Evaluation}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={userAccessLevel}
                    >
                        <LemonButton
                            size="small"
                            loading={transitioningIds.includes(backfill.id)}
                            disabledReason={
                                !evaluation?.enabled
                                    ? 'Re-enable the evaluation before retrying.'
                                    : hasActiveBackfill || creatingBackfill || transitioningIds.length > 0
                                      ? 'Wait for the active backfill operation to finish.'
                                      : undefined
                            }
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Retry remaining evaluations?',
                                    description:
                                        'This starts a new backfill with the same date range and filters, using the current evaluation settings. Existing results are kept. New evaluations are billed as usual.',
                                    primaryButton: {
                                        children: 'Retry remaining',
                                        onClick: () => retryBackfill(backfill.id),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        >
                            Retry remaining
                        </LemonButton>
                    </AccessControlAction>
                ) : null,
        },
    ]

    return (
        <div className="@container/backfills flex flex-col gap-4 max-w-6xl">
            <div className="rounded border p-4 flex flex-col gap-3">
                <div>
                    <h3 className="mb-1">Evaluate past {unitPlural}</h3>
                    <p className="text-muted mb-0">Run this evaluation over a past time range.</p>
                </div>

                {settleWait && (
                    <p className="text-muted mb-0">
                        This evaluation waits {settleWait} before it evaluates a {unit}, so a backfill can only cover
                        what is older than that.{' '}
                        <Link onClick={onConfigurationClick} data-attr="llma-eval-backfill-settle-configuration">
                            Change the wait
                        </Link>
                    </p>
                )}

                <div className="flex items-center gap-2 flex-wrap">
                    <DateFilter
                        size="small"
                        dateFrom={windowDateFrom}
                        dateTo={windowDateTo}
                        dateOptions={BACKFILL_DATE_OPTIONS}
                        onChange={(dateFrom, dateTo) => setWindowRange(dateFrom, dateTo)}
                        allowTimePrecision
                        allowFixedRangeWithTime
                    />
                    <LemonSwitch
                        bordered
                        checked={rerunExisting}
                        onChange={setRerunExisting}
                        label={`Include ${unitPlural} that already have a result`}
                        data-attr="llma-eval-backfill-rerun"
                    />
                </div>

                <LemonCollapse
                    panels={[
                        {
                            key: 'conditions',
                            header: 'Conditions',
                            dataAttr: 'llma-eval-backfill-conditions',
                            content: (
                                <EvaluationTriggers conditions={conditions} onChange={setConditions} unit={unit} />
                            ),
                        },
                    ]}
                />

                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className={estimateError ? 'text-danger' : 'text-muted'}>
                        {estimateLoading
                            ? 'Counting…'
                            : estimateError
                              ? estimateError
                              : estimateSummary
                                ? `${estimateSummary}${
                                      clampedWindow ? ` between ${clampedWindow.start} and ${clampedWindow.end}` : ''
                                  }`
                                : null}
                    </span>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Evaluation}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={userAccessLevel}
                    >
                        <LemonButton
                            type="primary"
                            onClick={confirmStart}
                            loading={creatingBackfill}
                            disabledReason={startDisabledReason}
                            data-attr="llma-eval-backfill-start"
                        >
                            Start backfill
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

            {/* The table's own empty state carries this error when there is nothing to list, so the
                banner covers the rows-on-screen case: a failing poll leaves stale progress with
                the table still drawn, and without this the user reads a live run as stalled. */}
            {backfillsError && backfills.length > 0 && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadBackfills(),
                        loading: backfillsLoading,
                        'data-attr': 'llma-eval-backfill-retry',
                    }}
                >
                    {backfillsError}
                </LemonBanner>
            )}

            <LemonTable
                dataSource={backfills}
                columns={columns}
                loading={backfillsLoading}
                rowKey="id"
                expandable={{
                    // -1 leaves a row on LemonTable's own toggle state, so only a "+N more" click forces one open.
                    isRowExpanded: (backfill) => (expandedBackfillIds.includes(backfill.id) ? 1 : -1),
                    onRowExpand: (backfill) => expandBackfill(backfill.id),
                    onRowCollapse: (backfill) => collapseBackfill(backfill.id),
                    expandedRowRender: (backfill) => {
                        const leftBehind = backfillLeftBehindLabel(backfill)
                        const lateArrivals = backfillLateArrivalCount(backfill)
                        const liveCovered = backfillLiveCoveredCount(backfill)
                        return (
                            <div className="flex flex-col items-start justify-between gap-4 px-2 py-3 @min-[48rem]/backfills:flex-row @min-[48rem]/backfills:items-center">
                                <div className="flex flex-col gap-2 min-w-0">
                                    {backfill.status === 'interrupted' && (
                                        <LemonBanner type="warning">
                                            {backfill.status_reason === 'evaluation_disabled'
                                                ? 'The evaluation was disabled. Check its configuration and provider key, then re-enable it and retry remaining.'
                                                : 'The backfill stopped before finishing. Check the evaluation configuration, then retry remaining.'}
                                        </LemonBanner>
                                    )}
                                    {!!backfill.failed_count && (
                                        <span>
                                            {backfill.failed_count.toLocaleString('en-US')} failed. Retry remaining to
                                            try again.
                                        </span>
                                    )}
                                    {backfill.conditions.map((condition, index) => (
                                        <div key={index} className="flex items-center gap-1 flex-wrap">
                                            <ConditionSetScope
                                                condition={condition}
                                                unitPlural={backfillUnitPlural(backfill)}
                                            />
                                            <span className="text-muted whitespace-nowrap">
                                                {backfillSamplingLabel(condition)}
                                            </span>
                                        </div>
                                    ))}
                                    <div className="flex items-center gap-2 flex-wrap text-muted">
                                        <span className="flex items-center gap-1 flex-wrap">
                                            <TZLabel
                                                time={backfill.window_start}
                                                timestampStyle="absolute"
                                                {...WINDOW_TIME_FORMAT}
                                            />
                                            <span>→</span>
                                            <TZLabel
                                                time={backfill.window_end}
                                                timestampStyle="absolute"
                                                {...WINDOW_TIME_FORMAT}
                                            />
                                        </span>
                                        <span>·</span>
                                        <span>
                                            {backfill.dispatched_count.toLocaleString('en-US')} started,{' '}
                                            {backfill.skipped_count.toLocaleString('en-US')} skipped, out of{' '}
                                            {pluralize(backfill.total_count, backfill.target)}
                                            {backfill.rerun_existing
                                                ? ' in range'
                                                : " that hadn't been evaluated when the backfill began"}
                                            {lateArrivals > 0 &&
                                                `, plus ${lateArrivals.toLocaleString('en-US')} that arrived during the run`}
                                        </span>
                                    </div>
                                    {liveCovered > 0 && (
                                        <div className="text-muted">
                                            {pluralize(liveCovered, backfill.target)}{' '}
                                            {liveCovered === 1 ? 'was' : 'were'} evaluated automatically before the
                                            backfill reached {liveCovered === 1 ? 'it' : 'them'}.
                                        </div>
                                    )}
                                    {leftBehind && <div className="text-warning">{leftBehind}</div>}
                                </div>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    to={
                                        combineUrl(router.values.location.pathname, {
                                            ...router.values.searchParams,
                                            evaluation_tab: 'runs',
                                            backfill_id: backfill.id,
                                        }).url
                                    }
                                    data-attr="llma-eval-backfill-view-results"
                                >
                                    View results from this run
                                </LemonButton>
                            </div>
                        )
                    },
                }}
                emptyState={
                    backfillsError ? (
                        <div className="flex items-center justify-center gap-2 flex-wrap">
                            <span className="text-danger">{backfillsError}</span>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => loadBackfills()}
                                data-attr="llma-eval-backfill-retry"
                            >
                                Retry
                            </LemonButton>
                        </div>
                    ) : (
                        `No backfills yet. Pick a range above to evaluate past ${unitPlural}.`
                    )
                }
                data-attr="llma-eval-backfill-table"
            />
        </div>
    )
}
