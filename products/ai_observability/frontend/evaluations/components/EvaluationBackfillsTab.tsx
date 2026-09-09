import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
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
import { backfillRangeDateFormat, backfillSamplingLabel } from '../backfillConditions'
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
    running: { label: 'Running', type: 'success' },
    completed: { label: 'Completed', type: 'default' },
    cancelled: { label: 'Cancelled', type: 'muted' },
}

const WINDOW_TIME_FORMAT = { formatDate: 'MMM D, YYYY', formatTime: 'HH:mm' }

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
}

export function EvaluationBackfillsTab({ evaluationId, userAccessLevel }: EvaluationBackfillsTabProps): JSX.Element {
    const logic = evaluationBackfillsLogic({ evaluationId })
    const {
        backfills,
        backfillsError,
        backfillsLoading,
        clampedWindow,
        conditions,
        creatingBackfill,
        estimate,
        estimateError,
        estimateLoading,
        expandedBackfillIds,
        rerunExisting,
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
        expandBackfill,
        collapseBackfill,
        loadBackfills,
    } = useActions(logic)

    const unitPlural = pluralize(2, unit, undefined, false)

    const columns: LemonTableColumns<EvaluationBackfillApi> = [
        {
            title: 'Range',
            key: 'window',
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
            render: (_, backfill) => (
                <div className="flex items-center gap-1 flex-wrap">
                    <LemonTag type={BACKFILL_STATUS_TAG[backfill.status].type}>
                        {BACKFILL_STATUS_TAG[backfill.status].label}
                    </LemonTag>
                    {backfill.rerun_existing && (
                        <LemonTag type="muted" size="small">
                            Includes evaluated units
                        </LemonTag>
                    )}
                </div>
            ),
        },
        {
            title: 'Scope',
            key: 'conditions',
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
                    </div>
                )
            },
        },
        {
            title: 'Progress',
            key: 'progress',
            render: (_, backfill) => {
                // A unit counts as handled once dispatched, or skipped because the live path covered it.
                // A rerun over a window that keeps growing can hand back more than the total it
                // started from, so the progress it shows stops at that total.
                const handled = Math.min(backfill.dispatched_count + backfill.skipped_count, backfill.total_count)
                return (
                    <Tooltip
                        title={`${backfill.dispatched_count.toLocaleString('en-US')} dispatched, ${backfill.skipped_count.toLocaleString(
                            'en-US'
                        )} skipped`}
                    >
                        <div className="min-w-24">
                            <span className="whitespace-nowrap">
                                {handled.toLocaleString('en-US')} / {backfill.total_count.toLocaleString('en-US')}
                            </span>
                            <LemonProgress
                                className="mt-1"
                                percent={backfill.total_count > 0 ? (handled / backfill.total_count) * 100 : 0}
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
            render: (_, backfill) => <TZLabel time={backfill.created_at} />,
        },
        {
            title: 'Created by',
            key: 'created_by',
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
                ) : null,
        },
    ]

    return (
        <div className="flex flex-col gap-4 max-w-6xl">
            <div className="rounded border p-4 flex flex-col gap-3">
                <div>
                    <h3 className="mb-1">Evaluate past {unitPlural}</h3>
                    <p className="text-muted mb-0">
                        Run this evaluation over a time range that has already happened. Any {unit} that already has a
                        result is skipped, unless you turn that off below.
                    </p>
                </div>

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
                        label={`Evaluate ${unitPlural} that already have a result`}
                        data-attr="llma-eval-backfill-rerun"
                    />
                </div>

                <LemonCollapse
                    panels={[
                        {
                            key: 'conditions',
                            header: 'Conditions',
                            dataAttr: 'llma-eval-backfill-conditions',
                            content: <EvaluationTriggers conditions={conditions} onChange={setConditions} />,
                        },
                    ]}
                />

                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className={estimateError ? 'text-danger' : 'text-muted'}>
                        {estimateLoading
                            ? 'Counting…'
                            : estimateError
                              ? estimateError
                              : estimate
                                ? `${pluralize(estimate.total_units, estimate.unit)} would be evaluated${
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
                            onClick={createBackfill}
                            loading={creatingBackfill}
                            disabledReason={startDisabledReason}
                            data-attr="llma-eval-backfill-start"
                        >
                            Start backfill
                        </LemonButton>
                    </AccessControlAction>
                </div>
            </div>

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
                    expandedRowRender: (backfill) => (
                        <div className="flex flex-col gap-2 py-2">
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
                            <div className="flex items-center gap-1 flex-wrap">
                                <TZLabel
                                    time={backfill.window_start}
                                    timestampStyle="absolute"
                                    {...WINDOW_TIME_FORMAT}
                                />
                                <span className="text-muted">→</span>
                                <TZLabel time={backfill.window_end} timestampStyle="absolute" {...WINDOW_TIME_FORMAT} />
                            </div>
                        </div>
                    ),
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
