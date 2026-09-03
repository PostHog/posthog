import {
    IconApps,
    IconBug,
    IconCursorClick,
    IconEndpoints,
    IconCursor,
    IconDashboard,
    IconDatabase,
    IconDecisionTree,
    IconDownload,
    IconEye,
    IconFlask,
    IconHome,
    IconList,
    IconListCheck,
    IconLive,
    IconListTree,
    IconLlmAnalytics,
    IconMCP,
    IconLlmPromptManagement,
    IconMessage,
    IconNotebook,
    IconNotification,
    IconPeople,
    IconPieChart,
    IconPiggyBank,
    IconPlaylist,
    IconPulse,
    IconRewindPlay,
    IconRocket,
    IconShare,
    IconScatter,
    IconSpotlight,
    IconToggle,
    IconToolbar,
    IconTrends,
    IconWarning,
    IconSupport,
} from '@posthog/icons'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { APIScopeObject } from '~/types'

/**
 * Icon for an access-controlled resource. Resources listed here keep the icon they have had;
 * anything else falls through to the project tree's map, which has its own default icon, so a
 * resource added later still shows something rather than nothing.
 */
export function ScopeIcon(props: { scope: APIScopeObject }): JSX.Element | null {
    switch (props.scope) {
        case 'project':
            return <IconHome />
        case 'action':
            return <IconCursor />
        case 'customer_analytics':
            return <IconPeople />
        case 'activity_log':
            return <IconNotification />
        case 'dashboard':
            return <IconDashboard />
        case 'early_access_feature':
            return <IconRocket />
        case 'endpoint':
            return <IconEndpoints />
        case 'error_tracking':
            return <IconWarning />
        case 'event_definition':
            return <IconApps />
        case 'evaluation':
            return <IconListCheck />
        case 'experiment':
            return <IconFlask />
        case 'export':
            return <IconDownload />
        case 'external_data_source':
            return <IconDatabase />
        case 'warehouse_objects':
        case 'warehouse_table':
        case 'warehouse_view':
            return <IconDatabase />
        case 'feature_flag':
            return <IconToggle />
        case 'heatmap':
            return <IconCursorClick />
        case 'hog_flow':
            return <IconDecisionTree />
        case 'insight':
            return <IconTrends />
        case 'llm_analytics':
            return <IconLlmAnalytics />
        case 'llm_skill':
            return <IconLlmPromptManagement />
        case 'llm_playground':
            return <IconPlaylist />
        case 'ai_observability_clusters':
            return <IconScatter />
        case 'live_debugger':
            return <IconBug />
        case 'logs':
            return <IconLive />
        case 'mcp_analytics':
            return <IconMCP />
        case 'metrics':
            return <IconPulse />
        case 'notebook':
            return <IconNotebook />
        case 'product_tour':
            return <IconSpotlight />
        case 'property_definition':
            return <IconApps />
        case 'replay_scanner':
            return <IconEye />
        case 'revenue_analytics':
            return <IconPiggyBank />
        case 'session_recording':
            return <IconRewindPlay />
        case 'sharing_configuration':
            return <IconShare />
        case 'survey':
            return <IconMessage />
        case 'ticket':
            return <IconSupport />
        case 'tagger':
            return <IconList />
        case 'task':
            return <IconBug />
        case 'web_analytics':
            return <IconPieChart />
        case 'tracing':
            return <IconListTree />
        case 'toolbar':
            return <IconToolbar />
        default:
            return iconForType(props.scope as FileSystemIconType)
    }
}
