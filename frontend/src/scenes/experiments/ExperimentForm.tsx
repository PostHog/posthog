import './Experiment.scss'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonDivider, LemonInput, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { ExperimentVariantNumber } from 'lib/components/SeriesGlyph'
import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect } from 'react'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { InsightType } from '~/types'

import { EXPERIMENT_INSIGHT_ID } from './constants'
import { experimentLogic } from './experimentLogic'
import { ExperimentInsightCreator } from './MetricSelector'

const StepInfo = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)
    const { addExperimentGroup, removeExperimentGroup, moveToNextFormStep } = useActions(experimentLogic)

    return (
        <div>
            <div className="space-y-8">
                <div className="space-y-6 max-w-120">
                    <LemonField name="name" label="Name" help="Set an internal name for this experiment">
                        <LemonInput placeholder="Pricing page conversion" />
                    </LemonField>
                    <LemonField
                        name="feature_flag_key"
                        label="Feature flag key"
                        help="Experiments use a feature flag to trigger which elements to show/hide based on rollout conditions. You'll use this key in your code."
                    >
                        <LemonInput placeholder="pricing-page-conversion" />
                    </LemonField>
                    <LemonField name="description" label="Description">
                        <LemonTextArea placeholder="The goal of this experiment is ..." />
                    </LemonField>
                </div>
                <div className="mt-10">
                    <h3>Variants</h3>
                    <div>Add up to 9 variants to test against your control.</div>
                    <LemonDivider />
                    <div className="grid grid-cols-2 gap-4 max-w-160">
                        <div className="max-w-60">
                            <h3>Control</h3>
                            <div className="flex items-center">
                                <Group key={0} name={['parameters', 'feature_flag_variants', 0]}>
                                    <ExperimentVariantNumber index={0} className="h-7 w-7 text-base" />
                                    <LemonField name="key" className="ml-2 flex-grow">
                                        <LemonInput
                                            disabled
                                            data-attr="experiment-variant-key"
                                            data-key-index={0}
                                            className="ph-ignore-input"
                                            fullWidth
                                            autoComplete="off"
                                            autoCapitalize="off"
                                            autoCorrect="off"
                                            spellCheck={false}
                                        />
                                    </LemonField>
                                </Group>
                            </div>
                            <div className="text-muted text-xs mt-2">
                                Included automatically, cannot be edited or removed
                            </div>
                        </div>
                        <div className="max-w-100">
                            <h3>Test(s)</h3>
                            {experiment.parameters.feature_flag_variants?.map((_, index) => {
                                if (index === 0) {
                                    return null
                                }

                                return (
                                    <Group key={index} name={['parameters', 'feature_flag_variants', index]}>
                                        <div
                                            key={`variant-${index}`}
                                            className={`flex items-center space-x-2 ${index > 1 && 'mt-2'}`}
                                        >
                                            <ExperimentVariantNumber index={index} className="h-7 w-7 text-base" />
                                            <LemonField name="key" className="flex-grow">
                                                <LemonInput
                                                    data-attr="experiment-variant-key"
                                                    data-key-index={index.toString()}
                                                    className="ph-ignore-input"
                                                    fullWidth
                                                    autoComplete="off"
                                                    autoCapitalize="off"
                                                    autoCorrect="off"
                                                    spellCheck={false}
                                                />
                                            </LemonField>
                                            <div className={`${index === 1 && 'pr-9'}`}>
                                                {index !== 1 && (
                                                    <Tooltip title="Delete this variant" placement="top-start">
                                                        <LemonButton
                                                            size="small"
                                                            icon={<IconTrash />}
                                                            onClick={() => removeExperimentGroup(index)}
                                                        />
                                                    </Tooltip>
                                                )}
                                            </div>
                                        </div>
                                    </Group>
                                )
                            })}
                            <div className="text-muted text-xs ml-9 mr-20 mt-2">
                                Alphanumeric, hyphens and underscores only
                            </div>
                            {(experiment.parameters.feature_flag_variants.length ?? 0) < MAX_EXPERIMENT_VARIANTS && (
                                <LemonButton
                                    className="ml-9 mt-2"
                                    type="secondary"
                                    onClick={() => addExperimentGroup()}
                                    icon={<IconPlusSmall />}
                                    data-attr="add-test-variant"
                                >
                                    Add test variant
                                </LemonButton>
                            )}
                        </div>
                    </div>
                </div>
            </div>
            <LemonButton className="mt-2" type="primary" onClick={() => moveToNextFormStep()}>
                Continue
            </LemonButton>
        </div>
    )
}

const StepGoal = (): JSX.Element => {
    const { experiment, exposureAndSampleSize, experimentInsightType, groupTypes, aggregationLabel } =
        useValues(experimentLogic)
    const { setExperiment, setNewExperimentInsight, createExperiment } = useActions(experimentLogic)

    // insightLogic
    const logic = insightLogic({ dashboardItemId: EXPERIMENT_INSIGHT_ID })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query } = useValues(insightDataLogic(insightProps))

    return (
        <div>
            <div className="space-y-8">
                {groupTypes.size > 0 && (
                    <div>
                        <h3>Participant type</h3>
                        <div>
                            This sets default aggregation type for all metrics and feature flags. You can change this at
                            any time by updating the metric or feature flag.
                        </div>
                        <LemonDivider />
                        <LemonRadio
                            value={
                                experiment.parameters.aggregation_group_type_index != undefined
                                    ? experiment.parameters.aggregation_group_type_index
                                    : -1
                            }
                            onChange={(rawGroupTypeIndex) => {
                                const groupTypeIndex = rawGroupTypeIndex !== -1 ? rawGroupTypeIndex : undefined

                                setExperiment({
                                    parameters: {
                                        ...experiment.parameters,
                                        aggregation_group_type_index: groupTypeIndex ?? undefined,
                                    },
                                })
                                setNewExperimentInsight()
                            }}
                            options={[
                                { value: -1, label: 'Persons' },
                                ...Array.from(groupTypes.values()).map((groupType) => ({
                                    value: groupType.group_type_index,
                                    label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                                })),
                            ]}
                        />
                    </div>
                )}
                <div>
                    <h3>Goal type</h3>
                    <LemonDivider />
                    <LemonRadio
                        className="space-y-2 -mt-2"
                        value={experimentInsightType}
                        onChange={(val) => {
                            val &&
                                setNewExperimentInsight({
                                    insight: val,
                                    properties: experiment?.filters?.properties,
                                })
                        }}
                        options={[
                            {
                                value: InsightType.FUNNELS,
                                label: (
                                    <div className="translate-y-2">
                                        <div>Conversion funnel</div>
                                        <div className="text-xs text-muted">
                                            Track how many people complete a sequence of actions and/or events
                                        </div>
                                    </div>
                                ),
                            },
                            {
                                value: InsightType.TRENDS,
                                label: (
                                    <div className="translate-y-2">
                                        <div>Trend</div>
                                        <div className="text-xs text-muted">
                                            Track a cumulative total count of a specific event or action
                                        </div>
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
                <div>
                    <h3>Goal criteria</h3>
                    <div>
                        {experimentInsightType === InsightType.FUNNELS
                            ? "Create the funnel where you'd like to see an increased conversion rate."
                            : 'Create a trend goal to track change in a single metric.'}
                    </div>
                    <LemonDivider />
                    <div className="p-4 border rounded mt-4 w-full lg:w-3/4 bg-bg-light">
                        <ExperimentInsightCreator insightProps={insightProps} />
                    </div>
                </div>
                <div className="pb-4">
                    <h3>Goal preview</h3>
                    <div className="mt-4 w-full lg:w-3/4">
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <Query query={query} context={{ insightProps }} readOnly />
                        </BindLogic>
                    </div>
                </div>
            </div>
            <LemonButton
                className="mt-2"
                type="primary"
                onClick={() => {
                    const { exposure, sampleSize } = exposureAndSampleSize
                    createExperiment(true, exposure, sampleSize)
                }}
            >
                Save as draft
            </LemonButton>
        </div>
    )
}

export function ExperimentForm(): JSX.Element {
    const { currentFormStep, props } = useValues(experimentLogic)
    const { setCurrentFormStep } = useActions(experimentLogic)

    const stepComponents = {
        0: <StepInfo />,
        1: <StepGoal />,
    }
    const CurrentStepComponent = (currentFormStep && stepComponents[currentFormStep]) || <StepInfo />

    useEffect(() => {
        setCurrentFormStep(0)
    }, [])

    return (
        <div>
            {currentFormStep > 0 && (
                <LemonButton
                    icon={<IconChevronLeft />}
                    type="secondary"
                    className="my-4"
                    onClick={() => {
                        setCurrentFormStep(currentFormStep - 1)
                    }}
                >
                    Back
                </LemonButton>
            )}
            <Form
                id="experiment-step"
                logic={experimentLogic}
                formKey="experiment"
                props={props}
                enableFormOnSubmit
                className="space-y-6 experiment-form"
            >
                {CurrentStepComponent}
            </Form>
        </div>
    )
}
