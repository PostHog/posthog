import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy, IconEllipsis, IconPencil, IconStack, IconTarget, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDropdown, LemonMenu, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { experimentMetricsLogic } from 'scenes/experiments/experimentMetricsLogic'
import { isMetricThresholdCueVisible } from 'scenes/experiments/ExperimentMetricThreshold'
import { getExposureEventAndProperty } from 'scenes/experiments/exposureContract'
import { METRIC_CONTEXTS, experimentMetricModalLogic } from 'scenes/experiments/Metrics/experimentMetricModalLogic'
import { sharedMetricDetailsModalLogic } from 'scenes/experiments/Metrics/sharedMetricDetailsModalLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { urls } from 'scenes/urls'

import type { Breakdown, EventsNode, ExperimentMetric } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { MetricTitle } from './MetricTitle'
import { getMetricTag } from './utils'

const MAX_BREAKDOWNS = 3

// Helper function to get the exposure event from experiment
const getExposureEvent = (experiment: Experiment): string =>
    getExposureEventAndProperty({
        featureFlagKey: experiment.feature_flag_key,
        exposureCriteria: experiment.exposure_criteria,
    }).event

const AddBreakdownMenuItem = ({
    experiment,
    onChange,
}: {
    experiment: Experiment
    onChange: (breakdown: Breakdown) => void
}): JSX.Element => {
    const [dropdownOpen, setDropdownOpen] = useState(false)

    const exposureEvent = getExposureEvent(experiment)
    const metadataSource: EventsNode = {
        kind: NodeKind.EventsNode,
        event: exposureEvent,
    }
    const taxonomicGroupTypes = [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]

    return (
        <LemonDropdown
            placement="left-start"
            overlay={
                <TaxonomicFilter
                    onChange={(group, value) => {
                        const breakdownType =
                            group.type === TaxonomicFilterGroupType.PersonProperties ? 'person' : 'event'
                        onChange({ type: breakdownType, property: value?.toString() || '' })
                        setDropdownOpen(false)
                    }}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                    metadataSource={metadataSource}
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

export const MetricHeader = ({
    displayOrder,
    metric,
    metricType,
    isPrimaryMetric,
    experiment,
    onDuplicateMetricClick,
    onBreakdownChange,
    onDeleteMetricClick,
    readOnly,
}: {
    displayOrder?: number
    metric: ExperimentMetric
    metricType: any
    isPrimaryMetric: boolean
    experiment: Experiment
    onDuplicateMetricClick: (metric: ExperimentMetric) => void
    onBreakdownChange: (breakdown: Breakdown) => void
    onDeleteMetricClick?: (metric: ExperimentMetric) => void
    readOnly?: boolean
}): JSX.Element => {
    /**
     * This is necessary for legacy experiments support
     */
    const {
        openPrimaryMetricModal,
        openSecondaryMetricModal,
        openPrimarySharedMetricModal,
        openSecondarySharedMetricModal,
    } = useActions(modalsLogic)

    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { openSharedMetricDetailModal } = useActions(sharedMetricDetailsModalLogic)

    const [menuVisible, setMenuVisible] = useState(false)
    const closeMenu = (): void => setMenuVisible(false)

    const isSharedMetric = !!metric.isSharedMetric && !!metric.sharedMetricId

    const openEditModal = (): void => {
        if (isSharedMetric) {
            /**
             * this is for legacy experiments support
             */
            const openSharedModal = isPrimaryMetric ? openPrimarySharedMetricModal : openSecondarySharedMetricModal
            openSharedModal(metric.sharedMetricId!)

            openSharedMetricDetailModal(metric, METRIC_CONTEXTS[isPrimaryMetric ? 'primary' : 'secondary'])
            return
        }

        /**
         * this is for legacy experiments support
         */
        const openMetricModal = isPrimaryMetric ? openPrimaryMetricModal : openSecondaryMetricModal
        if (metric.uuid) {
            openMetricModal(metric.uuid)
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
                    <div className="text-sm text-secondary max-w-lg">
                        <p>
                            We'll take you to the form to customize and save this metric. Your new version will appear
                            in your shared metrics, ready to be added to your experiment.
                        </p>
                    </div>
                ),
                primaryButton: {
                    children: 'Duplicate metric',
                    to: urls.experimentsSharedMetric(metric.sharedMetricId!, 'duplicate'),
                    type: 'primary',
                    size: 'small',
                },
                secondaryButton: {
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

    const recalculationEnabled = useFeatureFlag('EXPERIMENTS_METRICS_RECALCULATION')
    const { isMetricRecalculating } = useValues(experimentMetricsLogic({ experiment }))
    const showRecalculatingTag = recalculationEnabled && isMetricRecalculating(metric.uuid)

    return (
        <div className="text-xs font-semibold flex flex-col justify-between h-full">
            <div className="deprecated-space-y-1">
                <div className="flex items-start justify-between gap-2 min-w-0">
                    <div className="text-xs font-semibold flex items-start min-w-0 flex-1">
                        {displayOrder !== undefined && <span className="mr-1 flex-shrink-0">{displayOrder + 1}.</span>}
                        <div className="min-w-0 flex-1">
                            <MetricTitle metric={metric} metricType={metricType} />
                        </div>
                    </div>
                    {!readOnly && (
                        <div className="flex flex-shrink-0 gap-1">
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                icon={<IconPencil />}
                                tooltip="Edit"
                                aria-label="Edit metric"
                                onClick={openEditModal}
                            />
                            <LemonMenu
                                placement="bottom-end"
                                visible={menuVisible}
                                onVisibilityChange={setMenuVisible}
                                closeOnClickInside={false}
                                items={
                                    [
                                        {
                                            items: [
                                                canAddBreakdown && {
                                                    label: () => (
                                                        <AddBreakdownMenuItem
                                                            experiment={experiment}
                                                            onChange={(breakdown) => {
                                                                onBreakdownChange(breakdown)
                                                                closeMenu()
                                                            }}
                                                        />
                                                    ),
                                                    custom: true,
                                                },
                                                {
                                                    label: 'Duplicate',
                                                    icon: <IconCopy />,
                                                    onClick: () => {
                                                        closeMenu()
                                                        handleDuplicate()
                                                    },
                                                },
                                            ].filter(Boolean) as any,
                                        },
                                        onDeleteMetricClick && {
                                            items: [
                                                {
                                                    label: isSharedMetric ? 'Remove from experiment' : 'Delete',
                                                    icon: <IconTrash />,
                                                    status: 'danger',
                                                    onClick: () => {
                                                        closeMenu()
                                                        handleDelete()
                                                    },
                                                },
                                            ],
                                        },
                                    ].filter(Boolean) as any
                                }
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
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    {showRecalculatingTag && (
                        <LemonTag type="highlight" size="medium" icon={<Spinner textColored />}>
                            Recalculating
                        </LemonTag>
                    )}
                    <LemonTag type="muted" size="small">
                        {getMetricTag(metric)}
                    </LemonTag>
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
