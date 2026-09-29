import {
    IconBell,
    IconMessage,
    IconPullRequest,
    IconPulse,
    IconRewindPlay,
    IconSparkles,
    IconTrends,
    IconWarning,
} from '@posthog/icons'

import { TodayReportIcon } from './todaySignalReports'

const REPORT_ICONS: Record<TodayReportIcon, JSX.Element> = {
    pr: <IconPullRequest />,
    replay: <IconRewindPlay />,
    error: <IconWarning />,
    llm: <IconSparkles />,
    survey: <IconMessage />,
    analytics: <IconTrends />,
    trace: <IconPulse />,
    inbox: <IconBell />,
}

export function TodayIcon({ icon }: { icon: TodayReportIcon }): JSX.Element {
    return REPORT_ICONS[icon]
}
