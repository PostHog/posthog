import { expectLogic } from 'kea-test-utils'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, FunnelsFilter, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelConversionWindowTimeUnit, InsightLogicProps } from '~/types'

import { funnelConversionWindowFilterLogic } from './funnelConversionWindowFilterLogic'

describe('funnelConversionWindowFilterLogic', () => {
    let logic: ReturnType<typeof funnelConversionWindowFilterLogic.build>
    let builtFunnelDataLogic: ReturnType<typeof funnelDataLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
        })
        initKeaTests()

        const props: InsightLogicProps = { dashboardItemId: undefined }

        const builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
        builtDataNodeLogic.mount()

        builtFunnelDataLogic = funnelDataLogic(props)
        builtFunnelDataLogic.mount()

        logic = funnelConversionWindowFilterLogic(props)
        logic.mount()
    })

    it('converts NaN to null', () => {
        expectLogic(logic, () => {
            logic.actions.setFunnelWindowInterval(NaN)
        }).toMatchValues({
            funnelWindowInterval: null,
        })
    })

    it.each([
        ['below min', FunnelConversionWindowTimeUnit.Day, 0, true],
        ['at min', FunnelConversionWindowTimeUnit.Day, 1, false],
        ['in range', FunnelConversionWindowTimeUnit.Day, 100, false],
        ['at max', FunnelConversionWindowTimeUnit.Day, 365, false],
        ['above max', FunnelConversionWindowTimeUnit.Day, 366, true],
        ['null interval', FunnelConversionWindowTimeUnit.Day, null, false],
    ])('validates %s as out of bounds: %s', (_, unit, interval, expectedOutOfBounds) => {
        expectLogic(logic, () => {
            logic.actions.setFunnelWindowIntervalUnit(unit)
            logic.actions.setFunnelWindowInterval(interval)
        }).toMatchValues({
            isOutOfBounds: expectedOutOfBounds,
        })
    })

    it('shows validation error when out of bounds', () => {
        expectLogic(logic, () => {
            logic.actions.setFunnelWindowIntervalUnit(FunnelConversionWindowTimeUnit.Hour)
            logic.actions.setFunnelWindowInterval(25)
        }).toMatchValues({
            validationError: 'Value must be between 1 and 24',
        })
    })

    describe('commitFilter', () => {
        beforeEach(() => {
            builtFunnelDataLogic.actions.updateQuerySource({
                kind: NodeKind.FunnelsQuery,
                series: [],
            } as FunnelsQuery)
        })

        it('commits valid values to insightFilter', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFunnelWindowInterval(10)
                logic.actions.setFunnelWindowIntervalUnit(FunnelConversionWindowTimeUnit.Hour)
                logic.actions.commitFilter()
            }).toFinishAllListeners()

            expect(builtFunnelDataLogic.values.insightFilter).toMatchObject({
                funnelWindowInterval: 10,
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Hour,
            })
        })

        it('does not commit when interval is null', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFunnelWindowInterval(null)
                logic.actions.commitFilter()
            }).toFinishAllListeners()

            expect((builtFunnelDataLogic.values.insightFilter as FunnelsFilter)?.funnelWindowInterval).toBeUndefined()
        })

        it('does not commit when out of bounds', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFunnelWindowInterval(100)
                logic.actions.setFunnelWindowIntervalUnit(FunnelConversionWindowTimeUnit.Hour)
                logic.actions.commitFilter()
            }).toFinishAllListeners()

            expect((builtFunnelDataLogic.values.insightFilter as FunnelsFilter)?.funnelWindowInterval).not.toBe(100)
        })

        it('auto-commits when unit changes', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFunnelWindowInterval(5)
                logic.actions.setFunnelWindowIntervalUnit(FunnelConversionWindowTimeUnit.Week)
            }).toFinishAllListeners()

            expect(builtFunnelDataLogic.values.insightFilter).toMatchObject({
                funnelWindowInterval: 5,
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Week,
            })
        })
    })

    it('syncs values from insightFilter', async () => {
        await expectLogic(logic, () => {
            builtFunnelDataLogic.actions.updateQuerySource({
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 30,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Minute,
                },
            } as FunnelsQuery)
        })
            .toFinishAllListeners()
            .toMatchValues({
                funnelWindowInterval: 30,
                funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Minute,
            })
    })
})
