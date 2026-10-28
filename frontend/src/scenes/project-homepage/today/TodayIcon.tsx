import {
    IconBell,
    IconCode,
    IconDatabase,
    IconGitLab,
    IconGithub,
    IconLinear,
    IconListCheck,
    IconLlmAnalytics,
    IconMessage,
    IconPullRequest,
    IconPulse,
    IconRewindPlay,
    IconSignal,
    IconSupport,
    IconTelescope,
    IconTrends,
    IconWarning,
} from '@posthog/icons'

import { IconSlack } from 'lib/lemon-ui/icons'

import { TodayReportIcon } from './todaySignalReports'

const REPORT_ICONS: Record<TodayReportIcon, JSX.Element> = {
    pr: <IconPullRequest />,
    replay: <IconRewindPlay />,
    error: <IconWarning />,
    llm: <IconLlmAnalytics />,
    support: <IconSupport />,
    survey: <IconMessage />,
    analytics: <IconTrends />,
    logs: <IconPulse />,
    alert: <IconBell />,
    scout: <IconTelescope />,
    github: <IconGithub />,
    gitlab: <IconGitLab />,
    linear: <IconLinear />,
    jira: <IconListCheck />,
    database: <IconDatabase />,
    signal: <IconSignal />,
    code: <IconCode />,
    slack: <IconSlack />,
}

export function TodayIcon({ icon }: { icon: TodayReportIcon }): JSX.Element {
    return REPORT_ICONS[icon]
}
