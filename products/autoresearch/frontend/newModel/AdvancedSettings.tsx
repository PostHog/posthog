import { useActions, useValues } from 'kea'

import { LemonCollapse, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { autoresearchNewLogic, populationSummary } from '../autoresearchNewLogic'
import { POPULATION_FILTER_GROUP_TYPES } from './DefinitionSentence'

export function AdvancedSettings(): JSX.Element {
    const { newPipeline, advancedOpen } = useValues(autoresearchNewLogic)
    const { setNewPipelineValues, setAdvancedOpen } = useActions(autoresearchNewLogic)

    return (
        <LemonCollapse
            activeKey={advancedOpen ? 'advanced' : null}
            onChange={(key) => setAdvancedOpen(key === 'advanced')}
            panels={[
                {
                    key: 'advanced',
                    header: 'Advanced',
                    dataAttr: 'autoresearch-new-advanced',
                    content: (
                        <div className="flex flex-col gap-4">
                            <LemonField
                                name="training_lookback_days"
                                label="Training lookback (days)"
                                info="How far back to pull training examples from. Larger windows give more data but may include stale behavior."
                            >
                                <LemonInput type="number" min={7} max={730} />
                            </LemonField>
                            <div className="flex flex-col gap-2">
                                <LemonSwitch
                                    label="Learn from different people than it scores"
                                    checked={newPipeline.separate_training_population}
                                    onChange={(checked) =>
                                        setNewPipelineValues({
                                            separate_training_population: checked,
                                            ...(checked && newPipeline.training_population.length === 0
                                                ? { training_population: newPipeline.inference_population }
                                                : {}),
                                        })
                                    }
                                    bordered
                                    data-attr="autoresearch-new-separate-training"
                                />
                                {newPipeline.separate_training_population && (
                                    <LemonField
                                        name="training_population"
                                        label="Training population"
                                        help={`Learns from ${populationSummary(
                                            newPipeline.training_population_kind,
                                            newPipeline.training_population
                                        )}.`}
                                        info="Who the model learns from. Often people with enough history to be informative, for example people who signed up."
                                    >
                                        {({ value, onChange }) => (
                                            <PropertyFilters
                                                pageKey="autoresearch-new-training-population"
                                                propertyFilters={value ?? []}
                                                onChange={(filters) => onChange(filters)}
                                                taxonomicGroupTypes={POPULATION_FILTER_GROUP_TYPES}
                                                buttonText="Add filter"
                                            />
                                        )}
                                    </LemonField>
                                )}
                            </div>
                            <LemonField
                                name="iteration_budget"
                                label="Experiment budget"
                                info="The most experiments the agent runs while it searches for a better model. Training stops earlier when the model stops improving."
                            >
                                <LemonInput type="number" min={1} max={500} />
                            </LemonField>
                        </div>
                    ),
                },
            ]}
        />
    )
}
