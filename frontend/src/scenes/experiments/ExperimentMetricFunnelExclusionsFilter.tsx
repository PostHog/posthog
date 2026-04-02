import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { IconPlus, IconTrash } from '@posthog/icons'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import {
    EventsNode,
    ExperimentFunnelMetric,
    ExperimentMetric,
    FunnelExclusion,
    NodeKind,
} from '~/queries/schema/schema-general'

function ExclusionStepInfo(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div>
                Exclusion steps let you filter out users who performed a specific event between funnel steps. Users who
                trigger the excluded event in the specified step range will not count as conversions.
            </div>
            <div>
                For example, exclude users who viewed a help article between signing up and purchasing to measure
                self-serve conversion.
            </div>
        </div>
    )
}

export function ExperimentMetricFunnelExclusionsFilter({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentFunnelMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
}): JSX.Element {
    const exclusions = metric.exclusions || []
    const numSteps = metric.series.length

    const handleAddExclusion = (): void => {
        const newExclusion: FunnelExclusion = {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            funnelFromStep: 0,
            funnelToStep: Math.max(numSteps - 1, 1),
        }
        handleSetMetric({
            ...metric,
            exclusions: [...exclusions, newExclusion],
        })
    }

    const handleRemoveExclusion = (index: number): void => {
        handleSetMetric({
            ...metric,
            exclusions: exclusions.filter((_, i) => i !== index),
        })
    }

    const handleUpdateExclusionEvent = (index: number, eventName: string): void => {
        const updated = [...exclusions]
        updated[index] = {
            ...updated[index],
            kind: NodeKind.EventsNode,
            event: eventName,
        } as FunnelExclusion
        handleSetMetric({
            ...metric,
            exclusions: updated,
        })
    }

    const handleUpdateExclusionRange = (
        index: number,
        field: 'funnelFromStep' | 'funnelToStep',
        value: number
    ): void => {
        const updated = [...exclusions]
        updated[index] = {
            ...updated[index],
            [field]: value,
        } as FunnelExclusion
        handleSetMetric({
            ...metric,
            exclusions: updated,
        })
    }

    const stepOptions = Array.from({ length: numSteps }, (_, i) => ({
        value: i,
        label: `Step ${i + 1}`,
    }))

    // Need at least 2 funnel steps to use exclusions
    if (numSteps < 2) {
        return <></>
    }

    return (
        <SceneSection title="Exclusion steps" titleHelper={<ExclusionStepInfo />} className="max-w-prose">
            <div className="flex flex-col gap-2">
                {exclusions.map((exclusion, index) => (
                    <div key={index} className="flex items-center gap-2 border rounded p-2">
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.Events}
                            value={(exclusion as EventsNode).event || '$pageview'}
                            onChange={(value) => handleUpdateExclusionEvent(index, value as string)}
                            placeholder="Select event"
                            type="secondary"
                            size="small"
                        />
                        <span className="text-muted text-xs whitespace-nowrap">between</span>
                        <LemonSelect
                            size="small"
                            value={exclusion.funnelFromStep}
                            onChange={(value) => handleUpdateExclusionRange(index, 'funnelFromStep', value)}
                            options={stepOptions.filter((o) => o.value < (exclusion.funnelToStep ?? numSteps - 1))}
                        />
                        <span className="text-muted text-xs whitespace-nowrap">and</span>
                        <LemonSelect
                            size="small"
                            value={exclusion.funnelToStep}
                            onChange={(value) => handleUpdateExclusionRange(index, 'funnelToStep', value)}
                            options={stepOptions.filter((o) => o.value > (exclusion.funnelFromStep ?? 0))}
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            size="small"
                            type="tertiary"
                            onClick={() => handleRemoveExclusion(index)}
                        />
                    </div>
                ))}
                <LemonButton
                    icon={<IconPlus />}
                    type="secondary"
                    size="small"
                    onClick={handleAddExclusion}
                    className="self-start"
                >
                    Add exclusion step
                </LemonButton>
            </div>
        </SceneSection>
    )
}
