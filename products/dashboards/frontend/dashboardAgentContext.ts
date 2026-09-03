import { DashboardPlacement } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { BUILDING_A_DASHBOARD_SKILL, DASHBOARD_MCP_TOOLS, INSIGHT_MCP_TOOLS } from './generated/agentContext'

export interface DashboardAgentContextDashboard {
    id: number
    name?: string | null
}

const SKILL_DISMISS_GROUP = 'dashboard-scene-skill'
const STATE_DISMISS_GROUP = 'dashboard-scene-state'

const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        'The dashboard skill and MCP tool catalog are already present in this context. Call the listed tools directly, ' +
        'and use the exec `info <tool>` command only when you need a full input schema.',
}

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: BUILDING_A_DASHBOARD_SKILL.name,
    label: 'Building a dashboard skill',
    dismissGroup: SKILL_DISMISS_GROUP,
}

const SKILL_CONTENT_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value: `Skill ${BUILDING_A_DASHBOARD_SKILL.name} (embedded): ${BUILDING_A_DASHBOARD_SKILL.content}`,
}

const TOOL_CONTEXT_ITEMS: AttachedContextItem[] = [...DASHBOARD_MCP_TOOLS, ...INSIGHT_MCP_TOOLS].map((tool) => ({
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value: `MCP tool ${tool.name}: ${tool.description}`,
}))

const CURRENT_DASHBOARD_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: STATE_DISMISS_GROUP,
    value: 'The dashboard item is the current dashboard. Use dashboard-get to inspect its saved tiles before making changes.',
}

export function buildDashboardAgentContext(dashboard: DashboardAgentContextDashboard): AttachedContextItem[] {
    return [
        {
            type: 'dashboard',
            key: dashboard.id,
            label: dashboard.name || 'Current dashboard',
            dismissGroup: STATE_DISMISS_GROUP,
        },
        CURRENT_DASHBOARD_CONTEXT_ITEM,
        PREAMBLE_CONTEXT_ITEM,
        SKILL_CHIP_CONTEXT_ITEM,
        SKILL_CONTENT_CONTEXT_ITEM,
        ...TOOL_CONTEXT_ITEMS,
    ]
}

export function dashboardAgentContextForPlacement(
    dashboard: DashboardAgentContextDashboard | null,
    placement: DashboardPlacement
): AttachedContextItem[] | null {
    return dashboard && placement === DashboardPlacement.Dashboard ? buildDashboardAgentContext(dashboard) : null
}
