import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    EXPOSURE_DEFAULT_EVENT,
    getActivationConfig,
    getExposureEventAndProperty,
    resolvedExposureEvent,
} from 'scenes/experiments/exposureContract'

import type { Breakdown, EventsNode } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

export interface MetricMenuAction {
    key: string
    label: string
    icon: JSX.Element
    dataAttr?: string
    disabledReason?: string
    danger?: boolean
    onSelect: () => void
}

export interface MetricMenuSection {
    key: 'details' | 'edit' | 'delete'
    items: MetricMenuAction[]
}

export interface MetricHeaderActionsProps {
    experiment: Experiment
    sections: MetricMenuSection[]
    canAddBreakdown: boolean
    onBreakdownChange: (breakdown: Breakdown) => void
    onEdit: () => void
}

// In activation mode breakdowns are attributed from the activation event, so property suggestions should come from it too.
const getExposureEvent = (experiment: Experiment): string => {
    const activationConfig = getActivationConfig(experiment.exposure_criteria)
    if (activationConfig && 'event' in activationConfig && activationConfig.event) {
        return activationConfig.event
    }
    return (
        getExposureEventAndProperty({
            featureFlagKey: experiment.feature_flag_key,
            exposureCriteria: experiment.exposure_criteria,
            resolvedExposureEvent: resolvedExposureEvent(experiment),
        }).event ?? EXPOSURE_DEFAULT_EVENT
    )
}

export function BreakdownTaxonomicFilter({
    experiment,
    onChange,
}: {
    experiment: Experiment
    onChange: (breakdown: Breakdown) => void
}): JSX.Element {
    const metadataSource: EventsNode = {
        kind: NodeKind.EventsNode,
        event: getExposureEvent(experiment),
    }

    return (
        <TaxonomicFilter
            onChange={(group, value) => {
                const breakdownType = group.type === TaxonomicFilterGroupType.PersonProperties ? 'person' : 'event'
                onChange({ type: breakdownType, property: value?.toString() || '' })
            }}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]}
            metadataSource={metadataSource}
        />
    )
}

export const DUPLICATE_SHARED_METRIC_TITLE = 'Duplicate this shared metric?'

export function DuplicateSharedMetricCopy(): JSX.Element {
    return (
        <>
            <p className="m-0">
                <b>As a single-use metric</b> adds an editable copy to this experiment only. Other experiments using the
                shared metric are unaffected.
            </p>
            <p className="m-0">
                <b>As a shared metric</b> takes you to the form to customize and save a new shared metric, ready to be
                added to any experiment.
            </p>
        </>
    )
}

export function deleteMetricCopy(isSharedMetric: boolean): { title: string; label: string; description: string } {
    return isSharedMetric
        ? {
              title: 'Remove this metric from the experiment?',
              label: 'Remove from experiment',
              description:
                  'This will remove the shared metric from this experiment. The shared metric itself will not be deleted.',
          }
        : {
              title: 'Delete this metric?',
              label: 'Delete metric',
              description:
                  'This will permanently remove this metric from the experiment. This action cannot be undone.',
          }
}
