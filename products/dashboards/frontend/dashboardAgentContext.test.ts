import { DashboardPlacement } from '~/types'

import { buildDashboardAgentContext, dashboardAgentContextForPlacement } from './dashboardAgentContext'
import {
    ALERT_MCP_TOOLS,
    BUILDING_A_DASHBOARD_SKILL,
    MANAGING_SUBSCRIPTIONS_SKILL,
    SUBSCRIPTION_MCP_TOOLS,
} from './generated/agentContext'

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

    it('embeds contract-accurate subscription create examples', () => {
        const createWorkflow = MANAGING_SUBSCRIPTIONS_SKILL.content
            .split('#### Step 5: Create with `subscriptions-create`')[1]
            .split('### Updating a subscription')[0]
        const createPayloads = [...createWorkflow.matchAll(/```json\n([\s\S]*?)\n```/g)].map((match) =>
            JSON.parse(match[1])
        )

        expect(createPayloads).toHaveLength(5)
        expect(new Set(createPayloads.map((payload) => payload.target_type))).toEqual(
            new Set(['email', 'slack', 'teams'])
        )
        expect(createPayloads).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    target_type: 'teams',
                    target_value: 'https://example.webhook.office.com/webhookb2/example-token',
                }),
            ])
        )
        expect(
            createPayloads.every(
                (payload) =>
                    payload.target_type &&
                    payload.target_value &&
                    payload.frequency &&
                    payload.interval === 1 &&
                    payload.start_date
            )
        ).toBe(true)
    })

    it('embeds contract-accurate subscription destination, update, and deletion guidance', () => {
        const { content, description } = MANAGING_SUBSCRIPTIONS_SKILL
        const normalizedContent = content.replace(/\s+/g, ' ')
        const deletionHeading = content.includes('### Deleting a subscription')
            ? '### Deleting a subscription'
            : '### Deactivating a subscription'
        const updateWorkflow = content.split('### Updating a subscription')[1].split(deletionHeading)[0]
        const updatePayloads = [...updateWorkflow.matchAll(/`(\{[^`]+\})`/g)].map((match) => JSON.parse(match[1]))
        const deleteWorkflow = content.split(deletionHeading)[1].split('## Defaults')[0]

        expect(description).toContain('email, Slack, or Microsoft Teams deliveries')
        expect(description).not.toContain('email, Slack, or webhook deliveries')
        expect(content).toContain('`target_type` as `email`, `slack`, or `teams`')
        expect(content).not.toContain('`target_type` as `email`, `slack`, or `webhook`')
        expect(content).toContain('Responses expose only the webhook host')
        expect(content).toContain('`send_test_now` defaults to `true` on create')
        expect(normalizedContent).toContain('It is not available on `subscriptions-partial-update`')
        expect(updatePayloads).not.toHaveLength(0)
        expect(updatePayloads.every((payload) => payload.id === 456)).toBe(true)
        expect(deleteWorkflow).toContain('Use `subscriptions-delete`')
        expect(deleteWorkflow).not.toContain('subscriptions-partial-update')
        expect(deleteWorkflow).not.toContain('"deleted": true')
    })

    it('embeds bare MCP tool names in the building dashboard skill', () => {
        expect(BUILDING_A_DASHBOARD_SKILL.content).not.toContain('posthog:')
        expect(BUILDING_A_DASHBOARD_SKILL.content).toEqual(expect.stringContaining('`dashboard-reorder-tiles`'))
        expect(BUILDING_A_DASHBOARD_SKILL.content).toEqual(expect.stringContaining('`dashboard-get`'))
        expect(BUILDING_A_DASHBOARD_SKILL.content).toEqual(expect.stringContaining('`dashboard-create-tile`'))
        expect(BUILDING_A_DASHBOARD_SKILL.content).toEqual(expect.stringContaining('`dashboard-widget-catalog-list`'))
        expect(BUILDING_A_DASHBOARD_SKILL.content).toEqual(expect.stringContaining('`dashboard-widgets-batch-add`'))
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
