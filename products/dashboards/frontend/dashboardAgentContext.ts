import { DashboardPlacement } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import {
    ALERT_MCP_TOOLS,
    BUILDING_A_DASHBOARD_SKILL,
    DASHBOARD_MCP_TOOLS,
    INSIGHT_MCP_TOOLS,
    MANAGING_SUBSCRIPTIONS_SKILL,
    SUBSCRIPTION_MCP_TOOLS,
} from './generated/agentContext'

export interface DashboardAgentContextDashboard {
    id: number
    name?: string | null
}

const BUILDING_SKILL_DISMISS_GROUP = 'dashboard-scene-building-skill'
const SUBSCRIPTIONS_SKILL_DISMISS_GROUP = 'dashboard-scene-subscriptions-skill'
const STATE_DISMISS_GROUP = 'dashboard-scene-state'

const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'The dashboard skills and MCP tool catalog are already present in this context. Run every PostHog MCP ' +
        'operation through `mcp__posthog__exec`: use `info <tool>` to inspect its full input schema and ' +
        '`call <tool> <json>` to execute it. The `info` and `call` results are authoritative.',
}

const BUILDING_SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: BUILDING_A_DASHBOARD_SKILL.name,
    label: 'Building a dashboard skill',
    dismissGroup: BUILDING_SKILL_DISMISS_GROUP,
}

const BUILDING_SKILL_CONTENT_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: BUILDING_SKILL_DISMISS_GROUP,
    value: `Skill ${BUILDING_A_DASHBOARD_SKILL.name} (embedded): ${BUILDING_A_DASHBOARD_SKILL.content}`,
}

const SUBSCRIPTIONS_SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: MANAGING_SUBSCRIPTIONS_SKILL.name,
    label: 'Managing subscriptions skill',
    dismissGroup: SUBSCRIPTIONS_SKILL_DISMISS_GROUP,
}

const SUBSCRIPTIONS_SKILL_CONTENT_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SUBSCRIPTIONS_SKILL_DISMISS_GROUP,
    value: `Skill ${MANAGING_SUBSCRIPTIONS_SKILL.name} (embedded): ${MANAGING_SUBSCRIPTIONS_SKILL.content}`,
}

const TOOL_CONTEXT_ITEMS: AttachedContextItem[] = [
    ...DASHBOARD_MCP_TOOLS,
    ...INSIGHT_MCP_TOOLS,
    ...SUBSCRIPTION_MCP_TOOLS,
    ...ALERT_MCP_TOOLS,
].map((tool) => ({
    type: 'instructions',
    hidden: true,
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
        BUILDING_SKILL_CHIP_CONTEXT_ITEM,
        BUILDING_SKILL_CONTENT_CONTEXT_ITEM,
        SUBSCRIPTIONS_SKILL_CHIP_CONTEXT_ITEM,
        SUBSCRIPTIONS_SKILL_CONTENT_CONTEXT_ITEM,
        ...TOOL_CONTEXT_ITEMS,
    ]
}

export function dashboardAgentContextForPlacement(
    dashboard: DashboardAgentContextDashboard | null,
    placement: DashboardPlacement
): AttachedContextItem[] | null {
    return dashboard && placement === DashboardPlacement.Dashboard ? buildDashboardAgentContext(dashboard) : null
}
