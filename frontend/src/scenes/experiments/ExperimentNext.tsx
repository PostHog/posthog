import './Experiment.scss'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonDivider, LemonInput, LemonTextArea, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { ExperimentVariantNumber } from 'lib/components/SeriesGlyph'
import { MAX_VARIANTS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import React, { useEffect } from 'react'

import { experimentLogic } from './experimentLogic'

const CaretRightIcon = ({ fontSize }: { fontSize: number }): JSX.Element => {
    return (
        <svg fill="#000000" width={`${fontSize}px`} height={`${fontSize}px`} viewBox="0 0 256 256">
            <path d="M96,212a4,4,0,0,1-2.82861-6.82837L170.34326,128,93.17139,50.82837a4.00009,4.00009,0,0,1,5.65722-5.65674l80,80a4,4,0,0,1,0,5.65674l-80,80A3.98805,3.98805,0,0,1,96,212Z" />
        </svg>
    )
}

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
                            {index > 0 && <CaretRightIcon fontSize={20} />}
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
    const { experiment, props } = useValues(experimentLogic)
    const { addExperimentGroup, removeExperimentGroup } = useActions(experimentLogic)

    return (
        <>
            <Form
                id="experiment-step"
                logic={experimentLogic}
                formKey="experiment"
                props={props}
                className="space-y-6 experiment-form"
            >
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
                                            <div className={`${index === 1 && 'invisible'}`}>
                                                <Tooltip title="Delete this variant" placement="bottomLeft">
                                                    <LemonButton
                                                        size="small"
                                                        icon={<IconTrash />}
                                                        onClick={() => removeExperimentGroup(index)}
                                                    />
                                                </Tooltip>
                                            </div>
                                        </div>
                                    </Group>
                                )
                            })}
                            <div className="text-muted text-xs ml-9 mr-20 mt-2">
                                Alphanumeric, hyphens and underscores only
                            </div>
                            {(experiment.parameters.feature_flag_variants.length ?? 0) < MAX_VARIANTS && (
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
                <LemonButton form="experiment-step" type="primary" onClick={() => {}}>
                    Continue
                </LemonButton>
            </Form>
        </>
    )
}

const StepGoal = (): JSX.Element => {
    return <div>Goal</div>
}

const StepCode = (): JSX.Element => {
    return <div>Code</div>
}

export function ExperimentNext(): JSX.Element {
    const { currentFormStep } = useValues(experimentLogic)
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
            {CurrentStepComponent}
        </div>
    )
}
