import { useActions, useValues } from 'kea'

import { Button, Field, FieldLabel, InputGroup, InputGroupAddon, InputGroupInput, Slider } from '@posthog/quill'

import { StepLayout } from '../components/StepLayout'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

const clampTarget = (value: number): number => Math.min(100, Math.max(1, Math.round(value)))

export function GoalStep(): JSX.Element {
    const { focus, resolvedTarget, displayName } = useValues(guidedOnboardingLogic)
    const { setTarget, next } = useActions(guidedOnboardingLogic)

    if (!focus) {
        return <></>
    }

    return (
        <StepLayout
            title={`Set a goal for ${displayName}`}
            description="You can change it later."
            primary={
                <Button variant="primary" onClick={next} data-attr="guided-onboarding-goal-continue">
                    Set goal
                </Button>
            }
        >
            <Field>
                <FieldLabel htmlFor="guided-onboarding-goal-input">
                    {focus.goalVerb} {focus.metric} by
                </FieldLabel>
                <div className="flex items-center gap-4">
                    <div className="w-32 shrink-0">
                        <InputGroup>
                            <InputGroupInput
                                id="guided-onboarding-goal-input"
                                type="number"
                                min={1}
                                max={100}
                                value={resolvedTarget}
                                onChange={(event) => {
                                    const value = Number(event.target.value)
                                    if (Number.isFinite(value) && event.target.value !== '') {
                                        setTarget(clampTarget(value))
                                    }
                                }}
                                data-attr="guided-onboarding-goal-input"
                            />
                            <InputGroupAddon align="inline-end">%</InputGroupAddon>
                        </InputGroup>
                    </div>
                    <Slider
                        min={1}
                        max={50}
                        step={1}
                        value={Math.min(resolvedTarget, 50)}
                        onValueChange={(value) => setTarget(clampTarget(Array.isArray(value) ? value[0] : value))}
                        aria-label="Goal target"
                        className="flex-1"
                    />
                </div>
            </Field>
        </StepLayout>
    )
}
