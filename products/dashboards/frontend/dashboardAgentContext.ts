import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

export interface DashboardAgentContextDashboard {
    id: number
    name?: string | null
}

const BUILDING_A_DASHBOARD_SKILL = 'building-a-dashboard'
const SKILL_DISMISS_GROUP = 'dashboard-scene-skill'
const DASHBOARD_DISMISS_GROUP = 'dashboard-scene-dashboard'

const SKILL_INSTRUCTION: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        `The user has a PostHog dashboard open. Load the ${BUILDING_A_DASHBOARD_SKILL} skill before your first ` +
        'tool call. Act through the dashboard and insight MCP tools using the exec `dashboard-*`, `dashboards-*`, ' +
        'and `insight-*` commands. Use dashboard-get to inspect the saved dashboard before changing it. Do not ' +
        'search for tools; use the exec `info <tool>` command when you need a full input schema.',
}

const SKILL_ITEM: AttachedContextItem = {
    type: 'skill',
    key: BUILDING_A_DASHBOARD_SKILL,
    label: 'Building a dashboard skill',
    dismissGroup: SKILL_DISMISS_GROUP,
}

const DASHBOARD_INSTRUCTION: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: DASHBOARD_DISMISS_GROUP,
    value:
        'The dashboard item identifies the dashboard open in the standard dashboard scene. The Open dashboard text ' +
        'item carries its current id, and the latest item wins over earlier dashboard context in this task. Use that ' +
        'id with dashboard-get when the user refers to this dashboard.',
}

export const DASHBOARD_AGENT_HEADLINES: string[] = [
    'How can I help with this dashboard?',
    'What would you like to change?',
]

export function buildDashboardAgentContext(dashboard: DashboardAgentContextDashboard): AttachedContextItem[] {
    return [
        SKILL_INSTRUCTION,
        SKILL_ITEM,
        DASHBOARD_INSTRUCTION,
        {
            type: 'dashboard',
            key: dashboard.id,
            label: dashboard.name || 'Current dashboard',
            dismissGroup: DASHBOARD_DISMISS_GROUP,
        },
        {
            type: 'text',
            hidden: true,
            value: `Open dashboard: ${JSON.stringify({ id: dashboard.id })}`,
            dismissGroup: DASHBOARD_DISMISS_GROUP,
        },
    ]
}
