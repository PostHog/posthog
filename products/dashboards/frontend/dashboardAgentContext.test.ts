import { DashboardPlacement } from '~/types'

import { buildDashboardAgentContext, dashboardAgentContextForPlacement } from './dashboardAgentContext'

describe('dashboardAgentContext', () => {
    it('attaches the current dashboard with the embedded skill and tool catalog', () => {
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
                    type: 'instructions',
                    hidden: true,
                    value: expect.stringContaining('MCP tool dashboard-create-tile:'),
                }),
                expect.objectContaining({
                    type: 'instructions',
                    hidden: true,
                    value: expect.stringContaining('MCP tool insight-create:'),
                }),
            ])
        )

        const dashboardItem = context.find((item) => item.type === 'dashboard')
        const currentDashboardInstruction = context.find(
            (item) => item.type === 'instructions' && item.value?.includes('current dashboard')
        )
        const skillItem = context.find((item) => item.type === 'skill')
        const skillAndToolItems = context.filter(
            (item) => item.type === 'skill' || (item.type === 'instructions' && item !== currentDashboardInstruction)
        )

        expect(dashboardItem?.dismissGroup).toBe(currentDashboardInstruction?.dismissGroup)
        expect(skillAndToolItems.every((item) => item.dismissGroup === skillItem?.dismissGroup)).toBe(true)
        expect(skillItem?.dismissGroup).not.toBe(dashboardItem?.dismissGroup)
        expect(
            context
                .filter((item) => item.type === 'instructions')
                .every((item) => !item.value?.includes('Growth overview'))
        ).toBe(true)
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
