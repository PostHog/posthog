import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { DashboardTemplateType, DashboardType } from '~/types'

import { applyTemplate, newDashboardLogic } from './newDashboardLogic'

describe('newDashboardLogic', () => {
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

    describe('createDashboardFromTemplate', () => {
        const template: DashboardTemplateType = {
            id: 'template-1',
            template_name: 'Weekly KPIs',
            tiles: [],
            scope: 'team',
        }
        let logic: ReturnType<typeof newDashboardLogic.build>

        beforeEach(() => {
            initKeaTests()
            logic = newDashboardLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            jest.restoreAllMocks()
        })

        it('stays loading while the dashboard is created, so a second click cannot create a duplicate', async () => {
            let resolveCreate: (dashboard: Partial<DashboardType>) => void = () => {}
            jest.spyOn(api, 'create').mockImplementation(
                () =>
                    new Promise((resolve) => {
                        resolveCreate = resolve
                    })
            )

            logic.actions.createDashboardFromTemplate(template, [], false)

            expect(logic.values.isLoading).toBe(true)

            resolveCreate({ id: 1, name: 'Weekly KPIs', tiles: [] })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.isLoading).toBe(false)
        })
    })
})
