import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    IconCopy,
    IconEllipsis,
    IconGraph,
    IconPencil,
    IconSort,
    IconStack,
    IconTarget,
    IconTrash,
} from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDropdown, LemonMenu, LemonMenuItem, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { experimentLogic, getSectionMetricUuids } from 'scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from 'scenes/experiments/experimentMetricsLogic'
import { isMetricThresholdCueVisible } from 'scenes/experiments/ExperimentMetricThreshold'
import { urls } from 'scenes/urls'

import type { Breakdown, ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import {
    METRIC_CONTEXTS,
    experimentMetricModalLogic,
} from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'
import { sharedMetricDetailsModalLogic } from 'products/experiments/frontend/modals/SharedMetricDetailsModal/sharedMetricDetailsModalLogic'

import {
    BreakdownTaxonomicFilter,
    type MetricHeaderActionsProps,
    type MetricMenuAction,
    type MetricMenuSection,
} from './metricHeaderActions'
import { MetricRetryDetails } from './MetricRetryState'
import { MetricTitle } from './MetricTitle'
import { MetricTypeTag } from './MetricTypeTag'
import { QuillMetricHeaderActions } from './QuillMetricHeaderActions'

const MAX_BREAKDOWNS = 3

const AddBreakdownMenuItem = ({
    experiment,
    onChange,
}: {
    experiment: Experiment
    onChange: (breakdown: Breakdown) => void
}): JSX.Element => {
    const [dropdownOpen, setDropdownOpen] = useState(false)

    return (
        <LemonDropdown
            placement="left-start"
            overlay={
                <BreakdownTaxonomicFilter
                    experiment={experiment}
                    onChange={(breakdown) => {
                        onChange(breakdown)
                        setDropdownOpen(false)
                    }}
                />
            }
            visible={dropdownOpen}
            onClickOutside={() => setDropdownOpen(false)}
        >
            <LemonButton size="small" fullWidth icon={<IconStack />} onClick={() => setDropdownOpen(!dropdownOpen)}>
                Add breakdown
            </LemonButton>
        </LemonDropdown>
    )
}

const getBreakdownMenuItem = (experiment: Experiment, onChange: (breakdown: Breakdown) => void): LemonMenuItem => ({
    label: () => <AddBreakdownMenuItem experiment={experiment} onChange={onChange} />,
    custom: true,
})

function MetricHeaderActions({
    experiment,
    sections,
    canAddBreakdown,
    onBreakdownChange,
    onEdit,
}: MetricHeaderActionsProps): JSX.Element {
    const [menuVisible, setMenuVisible] = useState(false)
    const closeMenu = (): void => setMenuVisible(false)

    const toMenuItem = (action: MetricMenuAction): LemonMenuItem => ({
        label: action.label,
        icon: action.icon,
        'data-attr': action.dataAttr,
        disabledReason: action.disabledReason,
        status: action.danger ? 'danger' : undefined,
        onClick: () => {
            closeMenu()
            action.onSelect()
        },
    })

    return (
        <div
            className={clsx(
                'flex flex-shrink-0 gap-1 transition-opacity',
                menuVisible
                    ? 'opacity-100'
                    : 'opacity-0 group-hover/metric-cell:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100'
            )}
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconPencil />}
                tooltip="Edit"
                aria-label="Edit metric"
                onClick={onEdit}
            />
            <LemonMenu
                placement="bottom-end"
                visible={menuVisible}
                onVisibilityChange={setMenuVisible}
                closeOnClickInside={false}
                items={sections.map((section) => ({
                    items: [
                        ...(section.key === 'edit' && canAddBreakdown
                            ? [
                                  getBreakdownMenuItem(experiment, (breakdown) => {
                                      onBreakdownChange(breakdown)
                                      closeMenu()
                                  }),
                              ]
                            : []),
                        ...section.items.map(toMenuItem),
                    ],
                }))}
            >
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconEllipsis />}
                    tooltip="More actions"
                    aria-label="More actions"
                />
            </LemonMenu>
        </div>
    )
}

export const MetricHeader = ({
    dragHandle,
    displayOrder,
    metric,
    isPrimaryMetric,
    experiment,
    onDuplicateMetricClick,
    onDuplicateAsSingleUseMetricClick,
    onBreakdownChange,
    onDeleteMetricClick,
    onViewDetailsClick,
    readOnly,
}: {
    dragHandle?: JSX.Element | null
    displayOrder?: number
    metric: ExperimentMetric
    isPrimaryMetric: boolean
    experiment: Experiment
    onDuplicateMetricClick: (metric: ExperimentMetric) => void
    onDuplicateAsSingleUseMetricClick: (metric: ExperimentMetric) => void
    onBreakdownChange: (breakdown: Breakdown) => void
    onDeleteMetricClick?: (metric: ExperimentMetric) => void
    onViewDetailsClick?: () => void
    readOnly?: boolean
}): JSX.Element => {
    const { moveMetricsBetweenSections } = useActions(experimentLogic)
    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { openSharedMetricDetailModal } = useActions(sharedMetricDetailsModalLogic)

    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')

    const isSharedMetric = !!metric.isSharedMetric && !!metric.sharedMetricId

    const openEditModal = (): void => {
        if (isSharedMetric) {
            openSharedMetricDetailModal(metric, METRIC_CONTEXTS[isPrimaryMetric ? 'primary' : 'secondary'])
            return
        }

        openExperimentMetricModal(METRIC_CONTEXTS[isPrimaryMetric ? 'primary' : 'secondary'], metric)
    }

    const handleDuplicate = (): void => {
        /**
         * For shared metrics we open the duplicate form
         * after a confirmation.
         */
        if (isSharedMetric) {
            LemonDialog.open({
                title: 'Duplicate this shared metric?',
                content: (
                    <div className="text-sm text-secondary max-w-lg deprecated-space-y-2">
                        <p>
                            <b>As a single-use metric</b> adds an editable copy to this experiment only. Other
                            experiments using the shared metric are unaffected.
                        </p>
                        <p>
                            <b>As a shared metric</b> takes you to the form to customize and save a new shared metric,
                            ready to be added to any experiment.
                        </p>
                    </div>
                ),
                primaryButton: {
                    children: 'Duplicate as single-use metric',
                    size: 'small',
                    onClick: () => onDuplicateAsSingleUseMetricClick(metric),
                },
                secondaryButton: {
                    children: 'Duplicate as shared metric',
                    to: urls.experimentsSharedMetric(metric.sharedMetricId!, 'duplicate'),
                    type: 'secondary',
                    size: 'small',
                },
                tertiaryButton: {
                    children: 'Cancel',
                    type: 'tertiary',
                    size: 'small',
                },
            })
            return
        }

        // regular metrics just get duplicated
        onDuplicateMetricClick(metric)
    }

    const handleDelete = (): void => {
        if (!onDeleteMetricClick) {
            return
        }

        const deleteLabel = isSharedMetric ? 'Remove from experiment' : 'Delete metric'
        const description = isSharedMetric
            ? 'This will remove the shared metric from this experiment. The shared metric itself will not be deleted.'
            : 'This will permanently remove this metric from the experiment. This action cannot be undone.'

        LemonDialog.open({
            title: isSharedMetric ? 'Remove this metric from the experiment?' : 'Delete this metric?',
            content: <div className="text-sm text-secondary max-w-lg">{description}</div>,
            primaryButton: {
                children: deleteLabel,
                status: 'danger',
                type: 'primary',
                size: 'small',
                onClick: () => onDeleteMetricClick(metric),
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    const canAddBreakdown = (metric.breakdownFilter?.breakdowns || []).length < MAX_BREAKDOWNS

    const metricUuid = metric.uuid
    const sectionUuids =
        (isPrimaryMetric ? experiment.primary_metrics_ordered_uuids : experiment.secondary_metrics_ordered_uuids) ?? []
    // An experiment still has to measure something, so the last primary metric can't leave. Counted
    // from the metrics themselves, because the ordering array is a display hint that can hold stale uuids.
    const isLastPrimaryMetric = isPrimaryMetric && getSectionMetricUuids(experiment, false).length <= 1

    const handleMoveSection = (): void => {
        // The menu item only renders when the metric has a uuid.
        if (!metricUuid) {
            return
        }

        moveMetricsBetweenSections(isPrimaryMetric === false, sectionUuids, [], [metricUuid])
    }

    const { isMetricRecalculating, metricRetries } = useValues(experimentMetricsLogic({ experiment }))
    const showRecalculatingTag = isMetricRecalculating(metric.uuid)
    const metricRetry = metric.uuid ? metricRetries[metric.uuid] : undefined

    const editItems: MetricMenuAction[] = [
        { key: 'duplicate', label: 'Duplicate', icon: <IconCopy />, onSelect: handleDuplicate },
    ]
    if (metricUuid) {
        editItems.push({
            key: 'move',
            label: isPrimaryMetric ? 'Make secondary metric' : 'Make primary metric',
            icon: <IconSort />,
            disabledReason: isLastPrimaryMetric ? 'An experiment needs at least one primary metric' : undefined,
            onSelect: handleMoveSection,
        })
    }
    const sections: MetricMenuSection[] = [
        ...(onViewDetailsClick
            ? [
                  {
                      key: 'details' as const,
                      items: [
                          {
                              key: 'view-details',
                              label: 'View details',
                              icon: <IconGraph />,
                              dataAttr: 'experiment-metric-view-details',
                              onSelect: onViewDetailsClick,
                          },
                      ],
                  },
              ]
            : []),
        { key: 'edit', items: editItems },
        ...(onDeleteMetricClick
            ? [
                  {
                      key: 'delete' as const,
                      items: [
                          {
                              key: 'delete',
                              label: isSharedMetric ? 'Remove from experiment' : 'Delete',
                              icon: <IconTrash />,
                              danger: true,
                              onSelect: handleDelete,
                          },
                      ],
                  },
              ]
            : []),
    ]
    const actionsProps: MetricHeaderActionsProps = {
        experiment,
        sections,
        canAddBreakdown,
        onBreakdownChange,
        onEdit: openEditModal,
    }

    return (
        // The handle and the order number are their own columns, so the title and the tags below it
        // share one left edge instead of the tags starting back at the cell edge.
        <div className="text-xs font-semibold flex items-start gap-1">
            {dragHandle}
            {displayOrder !== undefined && <span className="flex-shrink-0">{displayOrder + 1}.</span>}
            <div className="flex flex-col flex-1 min-w-0 deprecated-space-y-1">
                <div className="flex items-start justify-between gap-2 min-w-0">
                    <div className="text-xs font-semibold flex items-start min-w-0 flex-1">
                        <div className="min-w-0 flex-1">
                            <MetricTitle metric={metric} />
                        </div>
                    </div>
                    {!readOnly &&
                        (todayRailNav && resultsRedesign ? (
                            <QuillMetricHeaderActions {...actionsProps} />
                        ) : (
                            <MetricHeaderActions {...actionsProps} />
                        ))}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    {(showRecalculatingTag || metricRetry) &&
                        (metricRetry ? (
                            <LemonDropdown
                                placement="bottom-start"
                                showArrow
                                trigger="hover"
                                closeOnClickInside={false}
                                overlay={<MetricRetryDetails retry={metricRetry} className="max-w-100 p-2" />}
                            >
                                <LemonTag type="warning" size="medium" icon={<Spinner textColored />}>
                                    Retry {metricRetry.attempt} of {metricRetry.max_attempts}
                                </LemonTag>
                            </LemonDropdown>
                        ) : (
                            <LemonTag type="highlight" size="medium" icon={<Spinner textColored />}>
                                Recalculating
                            </LemonTag>
                        ))}
                    <MetricTypeTag metric={metric} />
                    {isMetricThresholdCueVisible(metric) && (
                        <Tooltip
                            title={`Reports the percentage of users whose value reaches or exceeds ${metric.threshold}.`}
                        >
                            <LemonTag type="muted" size="small" icon={<IconTarget />}>
                                ≥ {metric.threshold}
                            </LemonTag>
                        </Tooltip>
                    )}
                    {experiment.parameters?.prompt_metadata && (
                        <LemonTag type="completion" size="small">
                            LLM
                        </LemonTag>
                    )}
                    {metric.goal === 'decrease' && (
                        <LemonTag type="highlight" size="small">
                            Goal: Decrease
                        </LemonTag>
                    )}
                    {metric.isSharedMetric && (
                        <LemonTag type="option" size="small">
                            Shared
                        </LemonTag>
                    )}
                </div>
            </div>
        </div>
    )
}
