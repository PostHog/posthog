import { useActions } from 'kea'
import { useState } from 'react'

import { IconCopy, IconPencil, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { METRIC_CONTEXTS, experimentMetricModalLogic } from 'scenes/experiments/Metrics/experimentMetricModalLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { isEventExposureConfig } from 'scenes/experiments/utils'
import { urls } from 'scenes/urls'

import type { EventsNode, ExperimentMetric } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { MetricTitle } from './MetricTitle'
import { getMetricTag } from './utils'

// Helper function to get the exposure event from experiment
const getExposureEvent = (experiment: Experiment): string => {
    const exposureConfig = experiment.exposure_criteria?.exposure_config
    if (!exposureConfig) {
        return '$feature_flag_called'
    }
    if (isEventExposureConfig(exposureConfig)) {
        return exposureConfig.event
    }
    // Fall back
    return '$feature_flag_called'
}

// AddBreakdownButton component for event property breakdowns
const AddBreakdownButton = ({
    experiment,
    onChange,
}: {
    experiment: Experiment
    onChange: (breakdown: { type: string; property: any }) => void
}): JSX.Element | null => {
    const [dropdownOpen, setDropdownOpen] = useState(false)

    /**
     * bail if we don't have an experiment
     * this could happen if the experiment has not been loaded yet
     * or if we are in the legacy experiment view
     */
    if (!experiment) {
        return null
    }

    // Create metadata source for the exposure event to filter properties
    const exposureEvent = getExposureEvent(experiment)
    const metadataSource: EventsNode = {
        kind: NodeKind.EventsNode,
        event: exposureEvent,
    }

    return (
        <LemonDropdown
            overlay={
                <TaxonomicFilter
                    onChange={(_, value) => {
                        onChange({ type: 'event', property: value })
                        setDropdownOpen(false)
                    }}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                    ]}
                    metadataSource={metadataSource}
                />
            }
            visible={dropdownOpen}
            onClickOutside={() => setDropdownOpen(false)}
        >
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={<IconPlusSmall />}
                onClick={() => setDropdownOpen(!dropdownOpen)}
            >
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
}: {
    displayOrder?: number
    metric: any
    metricType: any
    isPrimaryMetric: boolean
    experiment: Experiment
    onDuplicateMetricClick: (metric: ExperimentMetric) => void
}): JSX.Element => {
    const showBreakdownFilter = useFeatureFlag('EXPERIMENTS_BREAKDOWN_FILTER')

    /**
     * This is a bit overkill, since primary and secondary metric dialogs are
     * identical.
     * Also, it's not the responsibility of this component to understand
     * the difference between primary and secondary metrics.
     * For this component, primary and secondary are identical,
     * except for which modal to open.
     * The openModal function has to be provided as a dependency.
     */
    const {
        openPrimaryMetricModal,
        openSecondaryMetricModal,
        openPrimarySharedMetricModal,
        openSecondarySharedMetricModal,
    } = useActions(modalsLogic)

    const { openExperimentMetricModal } = useActions(experimentMetricModalLogic)

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
                    <div className="flex flex-col gap-1 flex-shrink-0 items-end">
                        <div className="flex gap-1">
                            <LemonButton
                                className="flex-shrink-0"
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil fontSize="12" />}
                                tooltip="Edit"
                                onClick={() => {
                                    if (metric.isSharedMetric) {
                                        const openSharedModal = isPrimaryMetric
                                            ? openPrimarySharedMetricModal
                                            : openSecondarySharedMetricModal
                                        openSharedModal(metric.sharedMetricId)
                                    } else {
                                        /**
                                         * this is for legacy experiments support
                                         */
                                        const openMetricModal = isPrimaryMetric
                                            ? openPrimaryMetricModal
                                            : openSecondaryMetricModal
                                        if (metric.uuid) {
                                            openMetricModal(metric.uuid)
                                        }

                                        openExperimentMetricModal(
                                            METRIC_CONTEXTS[isPrimaryMetric ? 'primary' : 'secondary'],
                                            metric
                                        )
                                    }
                                }}
                            />
                            <LemonButton
                                className="flex-shrink-0"
                                type="secondary"
                                size="xsmall"
                                icon={<IconCopy fontSize="12" />}
                                tooltip="Duplicate"
                                onClick={() => {
                                    /**
                                     * For shared metrics we open the duplicate form
                                     * after a confirmation.
                                     */
                                    if (metric.isSharedMetric) {
                                        LemonDialog.open({
                                            title: 'Duplicate this shared metric?',
                                            content: (
                                                <div className="text-sm text-secondary max-w-lg">
                                                    <p>
                                                        We'll take you to the form to customize and save this metric.
                                                        Your new version will appear in your shared metrics, ready to
                                                        add to your experiment.
                                                    </p>
                                                </div>
                                            ),
                                            primaryButton: {
                                                children: 'Duplicate metric',
                                                to: urls.experimentsSharedMetric(metric.sharedMetricId, 'duplicate'),
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
                                }}
                            />
                        </div>
                    </div>
                </div>
                <div className="deprecated-space-x-1">
                    <LemonTag type="muted" size="small">
                        {getMetricTag(metric)}
                    </LemonTag>
                    {metric.isSharedMetric && (
                        <LemonTag type="option" size="small">
                            Shared
                        </LemonTag>
                    )}
                </div>
            </div>
            {showBreakdownFilter && (
                <div className="flex justify-end items-end">
                    <AddBreakdownButton
                        experiment={experiment}
                        onChange={(breakdown) => {
                            /**
                             * TODO: Handle the breakdown selection
                             * this is to please the eslint gods
                             */
                            if (breakdown) {
                                return
                            }
                        }}
                    />
                </div>
            )}
        </div>
    )
}
