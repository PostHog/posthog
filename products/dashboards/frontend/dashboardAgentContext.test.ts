import { DashboardPlacement } from '~/types'

import { buildDashboardAgentContext, dashboardAgentContextForPlacement } from './dashboardAgentContext'
import { ALERT_MCP_TOOLS, MANAGING_SUBSCRIPTIONS_SKILL, SUBSCRIPTION_MCP_TOOLS } from './generated/agentContext'

describe('dashboardAgentContext', () => {
    it('attaches the current dashboard, both skills, and the tool catalog', () => {
        const context = buildDashboardAgentContext({ id: 5, name: 'Growth overview' })

        expect(context).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ type: 'dashboard', key: 5, label: 'Growth overview' }),
                expect.objectContaining({
                    type: 'skill',
                    key: 'building-a-dashboard',
                    label: 'Building a dashboard skill',
                }),
                expect.objectContaining({
                    type: 'skill',
                    key: 'managing-subscriptions',
                    label: 'Managing subscriptions skill',
                }),
                expect.objectContaining({
                    type: 'instructions',
                    hidden: true,
                    value: expect.stringContaining('MCP tool dashboard-create-tile:'),
                }),
                expect.objectContaining({
                    type: 'instructions',
                    hidden: true,
                    value: expect.stringContaining('MCP tool insight-create:'),
                }),
                expect.objectContaining({
                    type: 'instructions',
                    hidden: true,
                    value: expect.stringContaining('MCP tool subscriptions-create:'),
                }),
                expect.objectContaining({
                    type: 'instructions',
                    hidden: true,
                    value: expect.stringContaining('MCP tool alert-create:'),
                }),
            ])
        )
    })

    it('keeps the execution preamble and tool catalog attached when a skill is dismissed', () => {
        const context = buildDashboardAgentContext({ id: 5, name: 'Growth overview' })

        const preamble = context.find(
            (item) => item.type === 'instructions' && item.value?.includes('mcp__posthog__exec')
        )
        const toolItems = context.filter((item) => item.type === 'instructions' && item.value?.startsWith('MCP tool '))

        expect(preamble?.value).toContain('info <tool>')
        expect(preamble?.value).toContain('call <tool> <json>')
        expect(preamble?.value).toContain('authoritative')
        expect(preamble).not.toHaveProperty('dismissGroup')
        expect(toolItems).not.toHaveLength(0)
        expect(toolItems.every((item) => item.hidden && !item.dismissGroup)).toBe(true)
    })

    it('dismisses each skill independently from dashboard state', () => {
        const context = buildDashboardAgentContext({ id: 5, name: 'Growth overview' })

        const dashboardItem = context.find((item) => item.type === 'dashboard')
        const currentDashboardInstruction = context.find(
            (item) => item.type === 'instructions' && item.value?.includes('current dashboard')
        )
        const buildingSkillChip = context.find((item) => item.type === 'skill' && item.key === 'building-a-dashboard')
        const buildingSkillContent = context.find(
            (item) => item.type === 'instructions' && item.value?.startsWith('Skill building-a-dashboard (embedded):')
        )
        const subscriptionsSkillChip = context.find(
            (item) => item.type === 'skill' && item.key === 'managing-subscriptions'
        )
        const subscriptionsSkillContent = context.find(
            (item) => item.type === 'instructions' && item.value?.startsWith('Skill managing-subscriptions (embedded):')
        )

        expect(buildingSkillChip).not.toBeUndefined()
        expect(buildingSkillContent).not.toBeUndefined()
        expect(subscriptionsSkillChip).not.toBeUndefined()
        expect(subscriptionsSkillContent).not.toBeUndefined()
        expect(dashboardItem?.dismissGroup).toBe(currentDashboardInstruction?.dismissGroup)
        expect(buildingSkillChip?.dismissGroup).toBe(buildingSkillContent?.dismissGroup)
        expect(subscriptionsSkillChip?.dismissGroup).toBe(subscriptionsSkillContent?.dismissGroup)
        expect(buildingSkillChip?.dismissGroup).not.toBe(subscriptionsSkillChip?.dismissGroup)
        expect(buildingSkillChip?.dismissGroup).not.toBe(dashboardItem?.dismissGroup)
        expect(subscriptionsSkillChip?.dismissGroup).not.toBe(dashboardItem?.dismissGroup)
        expect(
            context
                .filter((item) => item.type === 'instructions')
                .every((item) => !item.value?.includes('Growth overview'))
        ).toBe(true)
    })

    it('generates only the curated subscription and alert tools for the dashboard scene', () => {
        expect(SUBSCRIPTION_MCP_TOOLS).toEqual([
            expect.objectContaining({ name: 'subscriptions-list' }),
            expect.objectContaining({ name: 'subscriptions-create' }),
        ])
        expect(ALERT_MCP_TOOLS).toEqual([
            expect.objectContaining({ name: 'alerts-list' }),
            expect.objectContaining({ name: 'alert-create' }),
        ])
    })

    it('embeds the managing subscriptions skill', () => {
        expect(MANAGING_SUBSCRIPTIONS_SKILL).toEqual(
            expect.objectContaining({
                name: 'managing-subscriptions',
                content: expect.stringContaining(
                    '- **`creating-ai-subscription`** — schedule a free-text AI report instead of an insight/dashboard snapshot'
                ),
            })
        )
    })

    test.each([
        DashboardPlacement.Public,
        DashboardPlacement.Export,
        DashboardPlacement.Builtin,
        DashboardPlacement.ProjectHomepage,
    ])('does not attach context for %s placement', (placement) => {
        expect(dashboardAgentContextForPlacement({ id: 5, name: 'Growth overview' }, placement)).toBeNull()
    })
})
