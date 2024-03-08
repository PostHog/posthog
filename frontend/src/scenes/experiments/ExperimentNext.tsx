import './Experiment.scss'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonDivider, LemonInput, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { ExperimentVariantNumber } from 'lib/components/SeriesGlyph'
import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import React, { useEffect } from 'react'

import { experimentLogic } from './experimentLogic'

const Header = (): JSX.Element => {
    const { currentFormStep } = useValues(experimentLogic)

    const steps = ['Info', 'Goal', 'Code']

    return (
        <div className="flex justify-between mb-6">
            <div className="w-1/2">
                <h2 className="text-left">New experiment</h2>
                <div>Measure the impact of changes against the baseline.</div>
            </div>
            <div className="w-1/2">
                <div className="flex items-center justify-end space-x-2">
                    {steps.map((step, index) => (
                        <React.Fragment key={index}>
                            {index > 0 && <IconChevronRight fontSize="24" />}
                            <div
                                className={`min-w-20 px-4 py-2 text-center cursor-default rounded ${
                                    currentFormStep === index ? 'font-bold' : 'text-muted'
                                }`}
                            >
                                {step}
                            </div>
                        </React.Fragment>
                    ))}
                </div>
            </div>
        </div>
    )
}

const StepInfo = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)
    const { addExperimentGroup, removeExperimentGroup, moveToNextFormStep } = useActions(experimentLogic)

    return (
        <div className="flex flex-col h-screen">
            <div className="flex-auto overflow-auto">
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
            <div className="sticky bottom-0 -mx-4 z-50 bg-bg-3000">
                <LemonDivider />
                <LemonButton className="px-4 pt-2 pb-3" type="primary" onClick={() => moveToNextFormStep()}>
                    Continue
                </LemonButton>
            </div>
        </div>
    )
}

const StepGoal = (): JSX.Element => {
    return <div>Goal</div>
}

const StepCode = (): JSX.Element => {
    return <div>Code</div>
}

export function ExperimentNext(): JSX.Element {
    const { currentFormStep, props } = useValues(experimentLogic)
    const { setCurrentFormStep } = useActions(experimentLogic)

    useEffect(() => {
        setCurrentFormStep(0)
    }, [])

    const stepComponents = {
        0: <StepInfo />,
        1: <StepGoal />,
        2: <StepCode />,
    }
    const CurrentStepComponent = (currentFormStep && stepComponents[currentFormStep]) || <StepInfo />

    return (
        <div>
            <Header />
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
