import {
    IconComponent,
    IconGlobe,
    IconLaptop,
    IconPlay,
    IconProps,
    IconRetention,
    IconShare,
    IconTarget,
    IconTrends,
    IconUserPaths,
    IconWarning,
} from '@posthog/icons'

export enum WebAnalyticsConcern {
    TRAFFIC = 'traffic',
    SOURCES = 'sources',
    PATHS = 'paths',
    GEOGRAPHY = 'geography',
    DEVICES = 'devices',
    RETENTION = 'retention',
    GOALS_CONVERSIONS = 'goals_conversions',
    ENGAGEMENT = 'engagement',
    ERRORS = 'errors',
}

export const CONCERN_LABELS: Record<WebAnalyticsConcern, string> = {
    [WebAnalyticsConcern.TRAFFIC]: 'Traffic & visitors',
    [WebAnalyticsConcern.SOURCES]: 'Where visitors come from',
    [WebAnalyticsConcern.PATHS]: 'Pages they land on and leave from',
    [WebAnalyticsConcern.GEOGRAPHY]: 'Where in the world',
    [WebAnalyticsConcern.DEVICES]: 'Devices and browsers',
    [WebAnalyticsConcern.RETENTION]: 'Whether they come back',
    [WebAnalyticsConcern.GOALS_CONVERSIONS]: 'Goals & conversions',
    [WebAnalyticsConcern.ENGAGEMENT]: 'Engagement & session replay',
    [WebAnalyticsConcern.ERRORS]: 'Errors & frustration',
}

export const CONCERN_ORDER: WebAnalyticsConcern[] = [
    WebAnalyticsConcern.TRAFFIC,
    WebAnalyticsConcern.SOURCES,
    WebAnalyticsConcern.PATHS,
    WebAnalyticsConcern.GEOGRAPHY,
    WebAnalyticsConcern.DEVICES,
    WebAnalyticsConcern.RETENTION,
    WebAnalyticsConcern.GOALS_CONVERSIONS,
    WebAnalyticsConcern.ENGAGEMENT,
    WebAnalyticsConcern.ERRORS,
]

export const CONCERN_ICONS: Record<WebAnalyticsConcern, IconComponent<IconProps>> = {
    [WebAnalyticsConcern.TRAFFIC]: IconTrends,
    [WebAnalyticsConcern.SOURCES]: IconShare,
    [WebAnalyticsConcern.PATHS]: IconUserPaths,
    [WebAnalyticsConcern.GEOGRAPHY]: IconGlobe,
    [WebAnalyticsConcern.DEVICES]: IconLaptop,
    [WebAnalyticsConcern.RETENTION]: IconRetention,
    [WebAnalyticsConcern.GOALS_CONVERSIONS]: IconTarget,
    [WebAnalyticsConcern.ENGAGEMENT]: IconPlay,
    [WebAnalyticsConcern.ERRORS]: IconWarning,
}

export const getFocusModeOnboardingSeenKey = (teamId: number): string => `web-analytics-focus-mode-${teamId}`
