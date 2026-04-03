import { ComponentType } from 'react'

import {
    IconBolt,
    IconClock,
    IconCode,
    IconCursorClick,
    IconFlag,
    IconGlobe,
    IconLaptop,
    IconPerson,
} from '@posthog/icons'

import { SurveyConditionSummary, SurveyConditionType } from 'scenes/surveys/utils'

export const SURVEY_CONDITION_ICON: Record<SurveyConditionType, ComponentType<{ className?: string }>> = {
    url: IconGlobe,
    selector: IconCode,
    device: IconLaptop,
    events: IconBolt,
    actions: IconCursorClick,
    flag: IconFlag,
    targeting: IconPerson,
    wait_period: IconClock,
}

export function SurveyConditionsList({ conditions }: { conditions: SurveyConditionSummary[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            {conditions.map(({ type, label, value }) => {
                const Icon = SURVEY_CONDITION_ICON[type]
                return (
                    <div key={type} className="flex items-center gap-2 text-sm">
                        <Icon className="text-muted shrink-0 text-base" />
                        <span className="text-muted whitespace-nowrap">{label}</span>
                        <span className="ml-auto text-right truncate">{value}</span>
                    </div>
                )
            })}
        </div>
    )
}
