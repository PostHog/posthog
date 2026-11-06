import { useActions, useValues } from 'kea'

import { Button, Field, FieldLabel, Input, Text } from '@posthog/quill'

import { ChoiceList } from '../components/ChoiceList'
import { ProductIcons } from '../components/ProductIcons'
import { StepLayout } from '../components/StepLayout'
import {
    CUSTOM_FOCUS_KEY,
    type FocusOption,
    INDUSTRY_LABELS,
    generalFocusOptions,
    industryFocusOptions,
} from '../focusOptions'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

export function FocusStep(): JSX.Element {
    const { industry, focusKey, customFocus } = useValues(guidedOnboardingLogic)
    const { setFocusKey, setCustomFocus, next } = useActions(guidedOnboardingLogic)
    const submitCustomFocus = (): void => {
        if (customFocus.trim()) {
            setFocusKey(CUSTOM_FOCUS_KEY)
            next()
        }
    }

    const sections: { title: string; options: FocusOption[] }[] = [
        {
            title: industry && industry !== 'other' ? INDUSTRY_LABELS[industry] : '',
            options: industryFocusOptions(industry),
        },
        { title: 'How people use it', options: generalFocusOptions('behavior') },
        { title: 'How it runs', options: generalFocusOptions('health') },
    ]

    return (
        <StepLayout
            title="What do you want to improve first?"
            description="Pick one. We set up PostHog to measure it from the first event."
        >
            {sections
                .filter(({ options }) => options.length > 0)
                .map(({ title, options }) => (
                    <div key={title} className="flex flex-col gap-2">
                        <Text size="xs" variant="muted" weight="medium">
                            {title}
                        </Text>
                        <ChoiceList
                            columns={2}
                            choices={options.map((option) => ({
                                value: option.key,
                                title: option.label,
                                trailing: <ProductIcons productKeys={option.products} />,
                            }))}
                            selected={focusKey}
                            onSelect={(key) => {
                                setFocusKey(key)
                                next()
                            }}
                            dataAttrPrefix="guided-onboarding-focus"
                        />
                    </div>
                ))}
            <Field>
                <FieldLabel htmlFor="guided-onboarding-focus-custom">Something else</FieldLabel>
                <div className="flex gap-2">
                    <Input
                        id="guided-onboarding-focus-custom"
                        placeholder="For example: get more people to finish their profile"
                        value={customFocus}
                        onChange={(event) => setCustomFocus(event.target.value)}
                        onKeyDown={(event) => event.key === 'Enter' && submitCustomFocus()}
                        data-attr="guided-onboarding-focus-custom"
                    />
                    <Button
                        variant="outline"
                        onClick={submitCustomFocus}
                        disabledReason={!customFocus.trim() ? 'Describe your goal first' : undefined}
                        data-attr="guided-onboarding-focus-custom-continue"
                    >
                        Use this goal
                    </Button>
                </div>
            </Field>
        </StepLayout>
    )
}
