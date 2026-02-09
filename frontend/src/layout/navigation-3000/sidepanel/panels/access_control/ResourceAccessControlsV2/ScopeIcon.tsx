import {
    IconApps,
    IconBug,
    IconCode2,
    IconCursor,
    IconDashboard,
    IconDatabase,
    IconFlask,
    IconHome,
    IconLive,
    IconLlmAnalytics,
    IconMessage,
    IconNotebook,
    IconNotification,
    IconPieChart,
    IconPiggyBank,
    IconRewindPlay,
    IconRocket,
    IconSpotlight,
    IconToggle,
    IconTrends,
    IconWarning,
} from '@posthog/icons'

import { APIScopeObject } from '~/types'

export function ScopeIcon(props: { scope: APIScopeObject }): JSX.Element | null {
    switch (props.scope) {
        case 'project':
            return <IconHome />
        case 'action':
            return <IconCursor />
        case 'activity_log':
            return <IconNotification />
        case 'dashboard':
            return <IconDashboard />
        case 'early_access_feature':
            return <IconRocket />
        case 'endpoint':
            return <IconCode2 />
        case 'error_tracking':
            return <IconWarning />
        case 'event_definition':
            return <IconApps />
        case 'experiment':
            return <IconFlask />
        case 'external_data_source':
            return <IconDatabase />
        case 'feature_flag':
            return <IconToggle />
        case 'insight':
            return <IconTrends />
        case 'llm_analytics':
            return <IconLlmAnalytics />
        case 'live_debugger':
            return <IconBug />
        case 'logs':
            return <IconLive />
        case 'notebook':
            return <IconNotebook />
        case 'product_tour':
            return <IconSpotlight />
        case 'property_definition':
            return <IconApps />
        case 'revenue_analytics':
            return <IconPiggyBank />
        case 'session_recording':
            return <IconRewindPlay />
        case 'survey':
            return <IconMessage />
        case 'task':
            return <IconBug />
        case 'web_analytics':
            return <IconPieChart />
        default:
            return null
    }
}
