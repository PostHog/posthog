import { useActions, useValues } from 'kea'

import {
    IconAI,
    IconBuilding,
    IconCart,
    IconCreditCard,
    IconGraduationCap,
    IconMapPin,
    IconNewspaper,
    IconPeople,
    IconPuzzle,
    IconSparkles,
    IconStethoscope,
    IconStore,
    IconTerminal,
} from '@posthog/icons'
import { Button, Field, FieldLabel, Input } from '@posthog/quill'

import { ChoiceList } from '../components/ChoiceList'
import { StepLayout } from '../components/StepLayout'
import { INDUSTRY_LABELS, type Industry } from '../focusOptions'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

const INDUSTRY_ICONS: Record<Industry, JSX.Element> = {
    ecommerce: <IconCart />,
    saas: <IconBuilding />,
    ai: <IconAI />,
    fintech: <IconCreditCard />,
    health: <IconStethoscope />,
    education: <IconGraduationCap />,
    media: <IconNewspaper />,
    marketplace: <IconStore />,
    social: <IconPeople />,
    gaming: <IconPuzzle />,
    devtools: <IconTerminal />,
    travel: <IconMapPin />,
    other: <IconSparkles />,
}

export function IndustryStep(): JSX.Element {
    const { industry, customIndustry, displayName } = useValues(guidedOnboardingLogic)
    const { setIndustry, setCustomIndustry, next } = useActions(guidedOnboardingLogic)

    return (
        <StepLayout
            title={`What kind of product is ${displayName}?`}
            description="We use this to suggest goals that fit."
            primary={
                industry === 'other' ? (
                    <Button variant="primary" onClick={next} data-attr="guided-onboarding-industry-continue">
                        Continue
                    </Button>
                ) : undefined
            }
        >
            <ChoiceList<Industry>
                columns={2}
                choices={(Object.keys(INDUSTRY_LABELS) as Industry[]).map((value) => ({
                    value,
                    title: INDUSTRY_LABELS[value],
                    icon: INDUSTRY_ICONS[value],
                }))}
                selected={industry}
                onSelect={setIndustry}
                dataAttrPrefix="guided-onboarding-industry"
            />
            {industry === 'other' && (
                <Field>
                    <FieldLabel htmlFor="guided-onboarding-industry-custom">Describe your product</FieldLabel>
                    <Input
                        id="guided-onboarding-industry-custom"
                        autoFocus
                        placeholder="For example: B2B analytics tool"
                        value={customIndustry}
                        onChange={(event) => setCustomIndustry(event.target.value)}
                        onKeyDown={(event) => event.key === 'Enter' && next()}
                        data-attr="guided-onboarding-industry-custom"
                    />
                </Field>
            )}
        </StepLayout>
    )
}
