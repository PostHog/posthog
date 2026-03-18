import { useState } from 'react'

import { DetectiveHog, MicrophoneHog, ProfessorHog, StarHog } from 'lib/components/hedgehogs'

import { WizardStep } from './surveyWizardLogic'

interface Tip {
    text: string
    Hog: typeof MicrophoneHog
}

// Tips focused on increasing survey completion rates
const TIPS_BY_STEP: Record<WizardStep, Tip[]> = {
    template: [
        { text: 'NPS is best for measuring overall loyalty. Use it quarterly for meaningful trends.', Hog: StarHog },
        { text: 'CSAT works great after specific interactions — support, purchase, feature use.', Hog: ProfessorHog },
        {
            text: 'PMF surveys help identify your most valuable users and understand your market fit.',
            Hog: DetectiveHog,
        },
    ],
    questions: [
        {
            text: 'Shorter surveys get more completions. Every extra question is a chance for someone to drop off.',
            Hog: ProfessorHog,
        },
        { text: 'Lead with your most important question — some users only answer the first one.', Hog: StarHog },
        {
            text: 'Rating scales are easier to answer than open text. Save open-ended questions for the end.',
            Hog: MicrophoneHog,
        },
        {
            text: 'Make your first question dead simple. Save harder questions for engaged respondents.',
            Hog: ProfessorHog,
        },
        { text: 'Be specific: "How was checkout?" beats "How was your experience?"', Hog: StarHog },
        { text: 'Every field is friction. Only ask what you truly need to know.', Hog: DetectiveHog },
    ],
    where: [
        { text: 'Surveys work best after someone takes an action — signup, purchase, feature use.', Hog: StarHog },
        { text: "Landing pages are usually too early. Users haven't formed opinions yet.", Hog: DetectiveHog },
        { text: 'Returning visitors are more likely to respond than first-time visitors.', Hog: ProfessorHog },
        {
            text: 'Exit-intent surveys on pricing pages can capture valuable "why not buy" feedback.',
            Hog: DetectiveHog,
        },
        { text: 'Show NPS surveys after users have experienced value, not immediately after signup.', Hog: StarHog },
        {
            text: 'Dashboard and settings pages catch users who are already engaged with your product.',
            Hog: MicrophoneHog,
        },
    ],
    when: [
        {
            text: 'Give users a moment to orient before showing a survey. Immediate popups get dismissed reflexively.',
            Hog: ProfessorHog,
        },
        { text: 'Trigger after success moments — completed tasks, achieved goals, resolved issues.', Hog: StarHog },
        { text: 'Avoid interrupting active workflows. Survey during natural pauses instead.', Hog: DetectiveHog },
        {
            text: 'Event-based triggers tend to catch users at better moments than time-based ones.',
            Hog: MicrophoneHog,
        },
        {
            text: 'Good trigger moments: after purchase, finishing onboarding, or resolving a support ticket.',
            Hog: StarHog,
        },
        {
            text: "Don't survey the same person too often. Quality drops when users feel over-surveyed.",
            Hog: ProfessorHog,
        },
    ],
    appearance: [
        {
            text: 'Match your brand colors for a cohesive experience. Surveys that look native get more responses.',
            Hog: StarHog,
        },
        {
            text: 'Dark themes work great for developer tools and evening products. Light themes feel friendlier.',
            Hog: ProfessorHog,
        },
        {
            text: 'High contrast between buttons and background makes the next action obvious.',
            Hog: DetectiveHog,
        },
    ],
    success: [],
}

interface MaxTipProps {
    step: WizardStep
}

export function MaxTip({ step }: MaxTipProps): JSX.Element | null {
    const tips = TIPS_BY_STEP[step]

    // Pick a random tip index once when the component mounts for this step
    const [tipIndices] = useState<Record<string, number>>(() => ({
        template: Math.floor(Math.random() * TIPS_BY_STEP.template.length),
        questions: Math.floor(Math.random() * TIPS_BY_STEP.questions.length),
        where: Math.floor(Math.random() * TIPS_BY_STEP.where.length),
        when: Math.floor(Math.random() * TIPS_BY_STEP.when.length),
        appearance: Math.floor(Math.random() * TIPS_BY_STEP.appearance.length),
    }))

    const selectedTip = tips?.[tipIndices[step]] ?? null

    if (!selectedTip) {
        return null
    }

    const { text, Hog } = selectedTip

    return (
        <div className="flex items-center justify-center gap-3 mt-10 pt-6 border-t border-border">
            <div className="flex-shrink-0 opacity-80">
                <Hog className="w-10 h-10" />
            </div>
            <span className="text-xs text-muted">{text}</span>
        </div>
    )
}
