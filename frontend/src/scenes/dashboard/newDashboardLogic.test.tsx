import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { DashboardTemplateType, DashboardType, SidePanelTab } from '~/types'

import { applyTemplate, newDashboardLogic } from './newDashboardLogic'

describe('template function in newDashboardLogic', () => {
    it('ignores unused variables', () => {
        expect(
            applyTemplate(
                { a: 'hello', b: 'hi' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            event: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                null
            )
        ).toEqual({ a: 'hello', b: 'hi' })
    })
    it('uses identified variables', () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}', b: 'hi' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            event: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                null
            )
        ).toEqual({
            a: {
                event: '$pageview',
            },
            b: 'hi',
        })
    })

    it('replaces variables in query based tiles', () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            id: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                NodeKind.TrendsQuery
            )
        ).toEqual({
            a: {
                event: '$pageview',
                kind: 'EventsNode',
                math: 'total',
            },
        })
    })

    it("removes the math property from query based tiles that don't support it", () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            id: '$pageview',
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                NodeKind.LifecycleQuery
            )
        ).toEqual({
            a: {
                event: '$pageview',
                kind: 'EventsNode',
            },
        })
    })

    it('removes the math property from retention insight tiles', () => {
        expect(
            applyTemplate(
                { a: '{VARIABLE_1}' },
                [
                    {
                        id: 'VARIABLE_1',
                        name: 'a',
                        default: {
                            id: '$pageview',
                            math: 'dau' as any,
                            type: 'events' as any,
                        },
                        description: 'The description of the variable',
                        required: true,
                        type: 'event',
                    },
                ],
                NodeKind.RetentionQuery
            )
        ).toEqual({
            a: {
                id: '$pageview',
                type: 'events',
            },
        })
    })
})

describe('Home dashboard creation', () => {
    let templateCreateRequestCount: number

    beforeEach(() => {
        templateCreateRequestCount = 0
        useMocks({
            patch: {
                '/api/environments/:team': async ({ request }) => {
                    const data = (await request.json()) as Record<string, unknown>
                    return [200, { ...MOCK_DEFAULT_TEAM, ...data }]
                },
            },
            post: {
                '/api/environments/:team/dashboards/': [201, { id: 123, name: 'My product analytics dashboard' }],
                '/api/environments/:team/dashboards/create_from_template_json/': async () => {
                    templateCreateRequestCount += 1
                    return [201, { id: 456, name: 'Product analytics starter' }]
                },
            },
        })
        initKeaTests()
        teamLogic.mount()
        sidePanelStateLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
    })

    it('sets a new blank dashboard as Home for the AI flow', async () => {
        const logic = newDashboardLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setAsHomeTabDashboardAfterCreation(true, true)
            logic.actions.addDashboard({ name: 'My product analytics dashboard', show: false })
        })
            .toDispatchActions(logic, ['submitNewDashboardSuccessWithResult'])
            .toDispatchActions(teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess'])

        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBe(123)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toContain('dashboard ID 123')
        expect(sidePanelStateLogic.values.selectedTabOptions).toContain('Ask me what I want to track')
    })

    it('waits for the Home assignment to be saved before opening AI', async () => {
        let finishPatch: () => void = () => {}
        const patchBarrier = new Promise<void>((resolve) => {
            finishPatch = resolve
        })
        useMocks({
            patch: {
                '/api/environments/:team': async ({ request }) => {
                    await patchBarrier
                    const data = (await request.json()) as Record<string, unknown>
                    return [200, { ...MOCK_DEFAULT_TEAM, ...data }]
                },
            },
        })

        const logic = newDashboardLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.submitNewDashboardSuccessWithResult({ id: 123 } as DashboardType, undefined, true, true)
        }).toDispatchActions(teamLogic, ['updateCurrentTeam'])

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBeNull()

        finishPatch()
        await expectLogic(logic).toDispatchActions(teamLogic, ['updateCurrentTeamSuccess']).toFinishAllListeners()

        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBe(123)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
    })

    it('does not open AI when the Home assignment fails', async () => {
        useMocks({
            patch: {
                '/api/environments/:team': [500, { type: 'server_error', detail: 'Unable to save Home' }],
            },
        })

        const logic = newDashboardLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.submitNewDashboardSuccessWithResult({ id: 123 } as DashboardType, undefined, true, true)
        })
            .toDispatchActions(teamLogic, ['updateCurrentTeamFailure'])
            .toFinishAllListeners()

        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBeNull()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    it('sets a dashboard created from a template as Home', async () => {
        const logic = newDashboardLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setAsHomeTabDashboardAfterCreation(true)
            logic.actions.createDashboardFromTemplate(
                { id: '7', template_name: 'Product analytics starter', tiles: [] } as DashboardTemplateType,
                [],
                false
            )
        })
            .toDispatchActions(logic, ['submitNewDashboardSuccessWithResult'])
            .toDispatchActions(teamLogic, ['updateCurrentTeam', 'updateCurrentTeamSuccess'])

        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBe(456)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    it('creates a template dashboard once when Create is clicked repeatedly', async () => {
        const logic = newDashboardLogic()
        logic.mount()
        const template = {
            id: 7,
            template_name: 'Product analytics starter',
            tiles: [],
        } as unknown as DashboardTemplateType

        await expectLogic(logic, () => {
            logic.actions.createDashboardFromTemplate(template, [], false)
            logic.actions.createDashboardFromTemplate(template, [], false)
        }).toFinishAllListeners()

        expect(templateCreateRequestCount).toBe(1)
    })

    it.each([false, true])('clears Home and AI intent on cancellation (AI: %s)', (openAI) => {
        const logic = newDashboardLogic()
        logic.mount()

        logic.actions.setAsHomeTabDashboardAfterCreation(true, openAI)
        logic.actions.hideNewDashboardModal()

        expect(logic.values.setAsHomeTabDashboardAfterCreation).toBe(false)
        expect(logic.values.openAIAfterCreation).toBe(false)
    })

    it('preserves Home and AI intent when retrying failed dashboard creation', async () => {
        let attempts = 0
        useMocks({
            post: {
                '/api/environments/:team/dashboards/': () => {
                    attempts += 1
                    return attempts === 1
                        ? [500, { type: 'server_error', detail: 'Unable to create dashboard' }]
                        : [201, { id: 123, name: 'My dashboard' }]
                },
            },
        })
        const logic = newDashboardLogic()
        logic.mount()
        logic.actions.setAsHomeTabDashboardAfterCreation(true, true)

        await expectLogic(logic, () => {
            logic.actions.addDashboard({ name: 'My dashboard', show: false })
        }).toFinishAllListeners()

        expect(logic.values.isLoading).toBe(false)
        expect(logic.values.setAsHomeTabDashboardAfterCreation).toBe(true)
        expect(logic.values.openAIAfterCreation).toBe(true)

        await expectLogic(logic, () => {
            logic.actions.addDashboard({ name: 'My dashboard', show: false })
        }).toFinishAllListeners()

        expect(attempts).toBe(2)
        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBe(123)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(logic.values.setAsHomeTabDashboardAfterCreation).toBe(false)
        expect(logic.values.openAIAfterCreation).toBe(false)
    })

    it('leaves Home unchanged after ordinary dashboard creation', async () => {
        const logic = newDashboardLogic()
        logic.mount()
        const dashboard = { id: 456, name: 'Another dashboard' } as DashboardType

        await expectLogic(logic, () => {
            logic.actions.submitNewDashboardSuccessWithResult(dashboard)
        }).toFinishAllListeners()

        expect(teamLogic.values.currentTeam?.home_tab_dashboard).toBeNull()
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })
})
