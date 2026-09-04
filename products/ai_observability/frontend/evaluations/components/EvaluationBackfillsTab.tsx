import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch, LemonTable, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType, DateMappingOption, UserBasicType } from '~/types'

import type { EvaluationBackfillApi, EvaluationBackfillStatusEnumApi } from '../../generated/api.schemas'
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

/** Raw instant, so two window bounds can be compared at a glance. */
const WINDOW_TIME_FORMAT = { formatDate: 'MMM D, YYYY', formatTime: 'HH:mm' }

function conditionPropertyKeys(backfill: EvaluationBackfillApi): string[] {
    const keys = backfill.conditions.flatMap((condition) =>
        (condition.properties ?? []).map((property) => String(property.key ?? ''))
    )
    return Array.from(new Set(keys.filter(Boolean)))
}

interface EvaluationBackfillsTabProps {
    evaluationId: string
    userAccessLevel?: AccessControlLevel
}

export function EvaluationBackfillsTab({ evaluationId, userAccessLevel }: EvaluationBackfillsTabProps): JSX.Element {
    const logic = evaluationBackfillsLogic({ evaluationId })
    const {
        backfills,
        backfillsLoading,
        conditions,
        creatingBackfill,
        estimate,
        estimateError,
        estimateLoading,
        rerunExisting,
        startDisabledReason,
        transitioningIds,
        unit,
        windowDateFrom,
        windowDateTo,
    } = useValues(logic)
    const { setWindowRange, setConditions, setRerunExisting, createBackfill, cancelBackfill } = useActions(logic)

    const unitPlural = pluralize(2, unit, undefined, false)

    const columns: LemonTableColumns<EvaluationBackfillApi> = [
        {
            title: 'Start',
            key: 'window_start',
            // `timestampStyle="absolute"` suppresses the Today/Yesterday substitution, so two rows
            // can be compared as exact instants while keeping TZLabel's timezone popover.
            render: (_, backfill) => (
                <TZLabel time={backfill.window_start} timestampStyle="absolute" {...WINDOW_TIME_FORMAT} />
            ),
        },
        {
            title: 'End',
            key: 'window_end',
            render: (_, backfill) => (
                <TZLabel time={backfill.window_end} timestampStyle="absolute" {...WINDOW_TIME_FORMAT} />
            ),
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, backfill) => (
                <LemonTag type={BACKFILL_STATUS_TAG[backfill.status].type}>
                    {BACKFILL_STATUS_TAG[backfill.status].label}
                </LemonTag>
            ),
        },
        {
            title: 'Progress',
            key: 'progress',
            render: (_, backfill) => {
                // Both count as handled: dispatched by this backfill, or skipped because the live
                // path had already covered the unit.
                const handled = backfill.dispatched_count + backfill.skipped_count
                return (
                    <Tooltip
                        title={`${backfill.dispatched_count.toLocaleString('en-US')} dispatched, ${backfill.skipped_count.toLocaleString(
                            'en-US'
                        )} skipped`}
                    >
                        <span className="whitespace-nowrap">
                            {handled.toLocaleString('en-US')} of {backfill.total_count.toLocaleString('en-US')}
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Conditions',
            key: 'conditions',
            render: (_, backfill) => {
                const keys = conditionPropertyKeys(backfill)
                return (
                    <Tooltip title={keys.length > 0 ? `Filters on ${keys.join(', ')}` : 'No property filters'}>
                        <span className="whitespace-nowrap">
                            {pluralize(backfill.conditions.length, 'condition set')}
                        </span>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Re-run',
            key: 'rerun_existing',
            render: (_, backfill) => <span>{backfill.rerun_existing ? 'Yes' : 'No'}</span>,
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
                                    disabledReason={transitioningIds.includes(backfill.id) ? 'Canceling…' : undefined}
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
                        label="Evaluate units that already have a result"
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
                                <div className="flex flex-col gap-4">
                                    <p className="text-muted mb-0">
                                        Copied from this evaluation. Changes only apply to this backfill.
                                    </p>
                                    <EvaluationTriggers conditions={conditions} onChange={setConditions} />
                                </div>
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
                              : estimate
                                ? `${pluralize(estimate.total_units, estimate.unit)} would be evaluated`
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
                emptyState={`No backfills yet. Pick a range above to evaluate past ${unitPlural}.`}
                data-attr="llma-eval-backfill-table"
            />
        </div>
    )
}
