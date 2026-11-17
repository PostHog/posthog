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
