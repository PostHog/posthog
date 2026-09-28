import {
    IconBell,
    IconCode,
    IconCreditCard,
    IconDatabase,
    IconFlask,
    IconHome,
    IconMessage,
    IconPullRequest,
    IconPulse,
    IconRewindPlay,
    IconSparkles,
    IconToggle,
    IconTrends,
    IconWarning,
} from '@posthog/icons'

import { TodayEvidenceKind, TodayScenarioId, TodayStoryIcon } from './todayTypes'

const STORY_ICONS: Record<TodayStoryIcon, JSX.Element> = {
    pr: <IconPullRequest />,
    experiment: <IconFlask />,
    replay: <IconRewindPlay />,
    error: <IconWarning />,
    llm: <IconSparkles />,
    survey: <IconMessage />,
    analytics: <IconTrends />,
    trace: <IconPulse />,
    inbox: <IconBell />,
    home: <IconHome />,
}

const EVIDENCE_ICONS: Record<TodayEvidenceKind, JSX.Element> = {
    analytics: <IconTrends />,
    code: <IconCode />,
    error: <IconWarning />,
    experiment: <IconFlask />,
    flag: <IconToggle />,
    replay: <IconRewindPlay />,
    survey: <IconMessage />,
    trace: <IconPulse />,
    warehouse: <IconDatabase />,
}

const SCENARIO_ICONS: Record<TodayScenarioId, JSX.Element> = {
    growth: <IconTrends />,
    checkout: <IconCreditCard />,
    'llm-cost': <IconSparkles />,
}

export function TodayIcon({
    story,
    evidence,
    scenario,
}: {
    story?: TodayStoryIcon
    evidence?: TodayEvidenceKind
    scenario?: TodayScenarioId
}): JSX.Element | null {
    if (story) {
        return STORY_ICONS[story]
    }
    if (evidence) {
        return EVIDENCE_ICONS[evidence]
    }
    if (scenario) {
        return SCENARIO_ICONS[scenario]
    }
    return null
}
