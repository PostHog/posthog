import { expectLogic } from 'kea-test-utils'
import timekeeper from 'timekeeper'

import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FunnelConversionWindowTimeUnit, FunnelVizType, InsightLogicProps, InsightType } from '~/types'

import {
    funnelResult,
    funnelResultTimeToConvert,
    funnelResultTimeToConvertWithoutConversions,
    funnelResultTrends,
    funnelResultWithBreakdown,
    funnelResultWithMultiBreakdown,
} from './__mocks__/funnelDataLogicMocks'
import { funnelDataLogic } from './funnelDataLogic'

let logic: ReturnType<typeof funnelDataLogic.build>
let builtDataNodeLogic: ReturnType<typeof dataNodeLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
}

async function initFunnelDataLogic(): Promise<void> {
    teamLogic.mount()
    await expectLogic(teamLogic).toFinishAllListeners()

    builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
    builtDataNodeLogic.mount()

    logic = funnelDataLogic(insightProps)
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
}

describe('funnelDataLogic', () => {
    beforeEach(async () => {
        initKeaTests(false)
        await initFunnelDataLogic()
    })

    describe('funnel viz types', () => {
        it('with non-funnel insight', () => {
            expect(logic.values.querySource).toBeNull()
            expect(logic.values.isStepsFunnel).toBeNull()
            expect(logic.values.isTimeToConvertFunnel).toBeNull()
            expect(logic.values.isTrendsFunnel).toBeNull()
        })

        it.each([
            ['missing funnelsFilter', undefined, true, false, false],
            ['steps viz', FunnelVizType.Steps, true, false, false],
            ['time to convert viz', FunnelVizType.TimeToConvert, false, true, false],
            ['trends viz', FunnelVizType.Trends, false, false, true],
        ] as const)('for %s', (_, funnelVizType, expectedIsSteps, expectedIsTimeToConvert, expectedIsTrends) => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                ...(funnelVizType && { funnelsFilter: { funnelVizType } }),
            }

            logic.actions.updateQuerySource(query)

            expect(logic.values.querySource).toMatchObject({ kind: NodeKind.FunnelsQuery })
            expect(logic.values.isStepsFunnel).toBe(expectedIsSteps)
            expect(logic.values.isTimeToConvertFunnel).toBe(expectedIsTimeToConvert)
            expect(logic.values.isTrendsFunnel).toBe(expectedIsTrends)
        })
    })

    describe('empty funnel', () => {
        it('with non-funnel insight', () => {
            expect(logic.values.querySource).toBeNull()
            expect(logic.values.isEmptyFunnel).toBeNull()
        })

        it('for empty funnel', () => {
            const query: FunnelsQuery = { kind: NodeKind.FunnelsQuery, series: [] }
            logic.actions.updateQuerySource(query)
            expect(logic.values.querySource).toMatchObject({ kind: NodeKind.FunnelsQuery })
            expect(logic.values.isEmptyFunnel).toBe(true)
        })

        it('for non-empty funnel', () => {
            const query: FunnelsQuery = { kind: NodeKind.FunnelsQuery, series: [{ kind: NodeKind.EventsNode }] }
            logic.actions.updateQuerySource(query)
            expect(logic.values.querySource).toMatchObject({ kind: NodeKind.FunnelsQuery })
            expect(logic.values.isEmptyFunnel).toBe(false)
        })
    })

    describe('based on insightDataLogic', () => {
        describe('results', () => {
            it.each([
                ['standard funnel', funnelResult.result, funnelResult.result],
                [
                    'breakdown',
                    funnelResultWithBreakdown.result,
                    expect.arrayContaining([
                        expect.arrayContaining([
                            expect.objectContaining({ breakdown_value: ['Chrome'], breakdown: ['Chrome'] }),
                        ]),
                    ]),
                ],
                ['breakdown with no results', [], expect.arrayContaining([])],
                [
                    'multi breakdown',
                    funnelResultWithMultiBreakdown.result,
                    expect.arrayContaining([
                        expect.arrayContaining([
                            expect.objectContaining({
                                breakdown_value: ['Chrome', 'Mac OS X'],
                                breakdown: ['Chrome', 'Mac OS X'],
                            }),
                        ]),
                    ]),
                ],
            ])('for %s', (_, inputResult, expectedResults) => {
                builtDataNodeLogic.actions.loadDataSuccess({ result: inputResult })
                expect(logic.values.results).toEqual(expectedResults)
            })
        })

        describe('steps', () => {
            it('with time-to-convert funnel returns empty steps', () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
                }
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: funnelResultTimeToConvert.result,
                })
                expect(logic.values.steps).toEqual([])
            })

            it.each([
                ['standard funnel', funnelResult.result, funnelResult.result],
                [
                    'breakdown',
                    funnelResultWithBreakdown.result,
                    expect.arrayContaining([
                        expect.objectContaining({
                            count: 201,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome'], count: 136 }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 53 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 12 }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 99,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome'], count: 66 }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 27 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 6 }),
                            ]),
                        }),
                    ]),
                ],
                [
                    'multi breakdown',
                    funnelResultWithMultiBreakdown.result,
                    expect.arrayContaining([
                        expect.objectContaining({
                            count: 69,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome', 'Mac OS X'], count: 49 }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 15 }),
                                expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 5 }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 37,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({ breakdown: ['Chrome', 'Mac OS X'], count: 26 }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 8 }),
                                expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 3 }),
                            ]),
                        }),
                    ]),
                ],
            ])('for %s', (_, inputResult, expectedSteps) => {
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: inputResult,
                })
                expect(logic.values.steps).toEqual(expectedSteps)
            })
        })

        describe('stepsWithConversionMetrics', () => {
            it.each([
                [
                    'standard funnel',
                    funnelResult.result,
                    expect.arrayContaining([
                        expect.objectContaining({
                            droppedOffFromPrevious: 0,
                            conversionRates: { fromBasisStep: 1, fromPrevious: 1, total: 1 },
                        }),
                        expect.objectContaining({
                            droppedOffFromPrevious: 157,
                            conversionRates: {
                                fromBasisStep: 0.46048109965635736,
                                fromPrevious: 0.46048109965635736,
                                total: 0.46048109965635736,
                            },
                        }),
                    ]),
                ],
                [
                    'breakdown',
                    funnelResultWithBreakdown.result,
                    expect.arrayContaining([
                        expect.objectContaining({
                            count: 201,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome'],
                                    count: 136,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 53 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 12 }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 99,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome'],
                                    count: 66,
                                    droppedOffFromPrevious: 70,
                                    conversionRates: {
                                        fromPrevious: 0.4852941176470588,
                                        total: 0.4852941176470588,
                                        fromBasisStep: 0.4852941176470588,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Firefox'], count: 27 }),
                                expect.objectContaining({ breakdown: ['Safari'], count: 6 }),
                            ]),
                        }),
                    ]),
                ],
                [
                    'multi breakdown',
                    funnelResultWithMultiBreakdown.result,
                    expect.arrayContaining([
                        expect.objectContaining({
                            count: 69,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome', 'Mac OS X'],
                                    count: 49,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 15 }),
                                expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 5 }),
                            ]),
                        }),
                        expect.objectContaining({
                            count: 37,
                            nested_breakdown: expect.arrayContaining([
                                expect.objectContaining({
                                    breakdown: ['Chrome', 'Mac OS X'],
                                    count: 26,
                                    droppedOffFromPrevious: 23,
                                    conversionRates: {
                                        fromPrevious: 0.5306122448979592,
                                        total: 0.5306122448979592,
                                        fromBasisStep: 0.5306122448979592,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({ breakdown: ['Chrome', 'Linux'], count: 8 }),
                                expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'], count: 3 }),
                            ]),
                        }),
                    ]),
                ],
            ])('for %s', (_, inputResult, expectedMetrics) => {
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: inputResult,
                })
                expect(logic.values.stepsWithConversionMetrics).toEqual(expectedMetrics)
            })
        })

        describe('flattenedBreakdowns', () => {
            it.each([
                [
                    'standard funnel',
                    funnelResult.result,
                    [
                        {
                            rowKey: 'baseline_0',
                            breakdown: ['baseline'],
                            breakdown_value: ['Baseline'],
                            isBaseline: true,
                            breakdownIndex: 0,
                            steps: [
                                expect.objectContaining({
                                    breakdown_value: 'Baseline',
                                    count: 291,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                }),
                                expect.objectContaining({
                                    breakdown_value: 'Baseline',
                                    count: 134,
                                    droppedOffFromPrevious: 157,
                                    conversionRates: {
                                        fromPrevious: 0.46048109965635736,
                                        total: 0.46048109965635736,
                                        fromBasisStep: 0.46048109965635736,
                                    },
                                }),
                            ],
                            conversionRates: { total: 0.46048109965635736 },
                        },
                    ],
                ],
                [
                    'breakdown',
                    funnelResultWithBreakdown.result,
                    [
                        expect.objectContaining({ breakdown: ['baseline'] }),
                        expect.objectContaining({
                            rowKey: 'Chrome_1',
                            breakdown: ['Chrome'],
                            breakdown_value: ['Chrome'],
                            isBaseline: false,
                            breakdownIndex: 1,
                            steps: [
                                expect.objectContaining({
                                    count: 136,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({
                                    count: 66,
                                    droppedOffFromPrevious: 70,
                                    conversionRates: {
                                        fromPrevious: 0.4852941176470588,
                                        total: 0.4852941176470588,
                                        fromBasisStep: 0.4852941176470588,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                            ],
                            conversionRates: { total: 0.4852941176470588 },
                            significant: false,
                        }),
                        expect.objectContaining({ breakdown: ['Firefox'] }),
                        expect.objectContaining({ breakdown: ['Safari'] }),
                    ],
                ],
                [
                    'multi breakdown',
                    funnelResultWithMultiBreakdown.result,
                    [
                        expect.objectContaining({ breakdown: ['baseline'] }),
                        expect.objectContaining({
                            rowKey: 'Chrome_Mac OS X_1',
                            breakdown: ['Chrome', 'Mac OS X'],
                            breakdown_value: ['Chrome', 'Mac OS X'],
                            isBaseline: false,
                            breakdownIndex: 1,
                            steps: [
                                expect.objectContaining({
                                    count: 49,
                                    droppedOffFromPrevious: 0,
                                    conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                                expect.objectContaining({
                                    count: 26,
                                    droppedOffFromPrevious: 23,
                                    conversionRates: {
                                        fromBasisStep: 0.5306122448979592,
                                        fromPrevious: 0.5306122448979592,
                                        total: 0.5306122448979592,
                                    },
                                    significant: { fromPrevious: false, fromBasisStep: false, total: false },
                                }),
                            ],
                            conversionRates: { total: 0.5306122448979592 },
                            significant: false,
                        }),
                        expect.objectContaining({ breakdown: ['Chrome', 'Linux'] }),
                        expect.objectContaining({ breakdown: ['Internet Explorer', 'Windows'] }),
                    ],
                ],
            ])('for %s', (_, inputResult, expectedBreakdowns) => {
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: inputResult,
                })
                expect(logic.values.flattenedBreakdowns).toEqual(expectedBreakdowns)
            })
        })

        describe('visibleStepsWithConversionMetrics', () => {
            it('for standard funnel', () => {
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: funnelResult.result,
                })

                expect(logic.values.visibleStepsWithConversionMetrics).toEqual([
                    expect.objectContaining({
                        name: '$pageview',
                        count: 291,
                        conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                    }),
                    expect.objectContaining({
                        name: '$pageview',
                        count: 134,
                        conversionRates: {
                            fromPrevious: 0.46048109965635736,
                            total: 0.46048109965635736,
                            fromBasisStep: 0.46048109965635736,
                        },
                        nested_breakdown: [expect.objectContaining({ breakdown_value: 'Baseline' })],
                    }),
                ])
            })

            it.each([
                [
                    'breakdown with hidden Firefox',
                    funnelResultWithBreakdown.result,
                    ['Firefox'],
                    [
                        expect.objectContaining({
                            name: '$pageview',
                            count: 201,
                            conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                        }),
                        expect.objectContaining({
                            name: '$pageview',
                            count: 99,
                            conversionRates: {
                                fromPrevious: 0.4925373134328358,
                                total: 0.4925373134328358,
                                fromBasisStep: 0.4925373134328358,
                            },
                            nested_breakdown: [
                                expect.objectContaining({ breakdown_value: 'Baseline', count: 99 }),
                                expect.objectContaining({ breakdown_value: ['Chrome'], count: 66 }),
                                expect.objectContaining({ breakdown_value: ['Safari'], count: 6 }),
                            ],
                        }),
                    ],
                ],
                [
                    'multi breakdown with hidden Chrome::Mac OS X',
                    funnelResultWithMultiBreakdown.result,
                    ['Chrome::Mac OS X'],
                    [
                        expect.objectContaining({
                            name: '$pageview',
                            count: 69,
                            conversionRates: { fromPrevious: 1, total: 1, fromBasisStep: 1 },
                        }),
                        expect.objectContaining({
                            name: '$pageview',
                            count: 37,
                            conversionRates: {
                                fromPrevious: 0.5362318840579711,
                                total: 0.5362318840579711,
                                fromBasisStep: 0.5362318840579711,
                            },
                            nested_breakdown: [
                                expect.objectContaining({ breakdown_value: 'Baseline', count: 37 }),
                                expect.objectContaining({ breakdown_value: ['Chrome', 'Linux'], count: 8 }),
                                expect.objectContaining({
                                    breakdown_value: ['Internet Explorer', 'Windows'],
                                    count: 3,
                                }),
                            ],
                        }),
                    ],
                ],
            ])('with %s', (_, inputResult, hiddenBreakdowns, expectedSteps) => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: { hiddenLegendBreakdowns: hiddenBreakdowns },
                }
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: inputResult,
                })

                expect(logic.values.visibleStepsWithConversionMetrics).toEqual(expectedSteps)
            })
        })
    })

    describe('time to convert funnel', () => {
        describe('timeConversionResults', () => {
            it('with time-to-convert funnel returns results', () => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
                }
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: funnelResultTimeToConvert.result,
                })

                expect(logic.values.timeConversionResults).toEqual(funnelResultTimeToConvert.result)
            })

            it('with other funnel returns null', () => {
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: funnelResult.result,
                })

                expect(logic.values.timeConversionResults).toBeNull()
            })
        })

        describe('histogramGraphData', () => {
            it.each([
                ['empty bins', { ...funnelResultTimeToConvert.result, bins: [] }, null],
                ['no conversions', funnelResultTimeToConvertWithoutConversions.result, []],
                [
                    'valid time-to-convert data',
                    funnelResultTimeToConvert.result,
                    [
                        { bin0: 4, bin1: 73591, count: 74, id: 4, label: '54.8%' },
                        { bin0: 73591, bin1: 147178, count: 24, id: 73591, label: '17.8%' },
                        { bin0: 147178, bin1: 220765, count: 24, id: 147178, label: '17.8%' },
                        { bin0: 220765, bin1: 294352, count: 10, id: 220765, label: '7.4%' },
                        { bin0: 294352, bin1: 367939, count: 2, id: 294352, label: '1.5%' },
                        { bin0: 367939, bin1: 441526, count: 1, id: 367939, label: '0.7%' },
                        { bin0: 441526, bin1: 515113, count: 0, id: 441526, label: '' },
                    ],
                ],
            ])('with %s', (_, inputResult, expectedData) => {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: { funnelVizType: FunnelVizType.TimeToConvert },
                }
                logic.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess({
                    filters: { insight: InsightType.FUNNELS },
                    result: inputResult,
                })

                expect(logic.values.histogramGraphData).toEqual(expectedData)
            })
        })
    })

    describe('hasFunnelResults', () => {
        it.each([
            ['steps viz', FunnelVizType.Steps, funnelResult.result],
            ['time to convert viz', FunnelVizType.TimeToConvert, funnelResultTimeToConvert.result],
            ['trends viz', FunnelVizType.Trends, funnelResultTrends.result],
        ])('for %s returns true when has results', (_, vizType, inputResult) => {
            builtDataNodeLogic.actions.loadDataSuccess({
                filters: { insight: InsightType.FUNNELS },
                result: inputResult,
            })
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: vizType },
            }
            logic.actions.updateQuerySource(query)

            expect(logic.values.hasFunnelResults).toBe(true)
        })
    })

    describe('conversionMetrics', () => {
        it.each([
            [
                'steps viz with multiple steps',
                FunnelVizType.Steps,
                funnelResult.result,
                { averageTime: 87098.67529697785, stepRate: 0.46048109965635736, totalRate: 0.46048109965635736 },
            ],
            [
                'time to convert viz',
                FunnelVizType.TimeToConvert,
                funnelResultTimeToConvert.result,
                { averageTime: 86456.76, stepRate: 0, totalRate: 0 },
            ],
            [
                'trends viz',
                FunnelVizType.Trends,
                funnelResultTrends.result,
                { averageTime: 0, stepRate: 0, totalRate: 0.7120000000000001 },
            ],
        ])('for %s', (_, vizType, inputResult, expectedMetrics) => {
            builtDataNodeLogic.actions.loadDataSuccess({
                filters: { insight: InsightType.FUNNELS },
                result: inputResult,
            })
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: { funnelVizType: vizType },
            }
            logic.actions.updateQuerySource(query)

            expect(logic.values.conversionMetrics).toEqual(expectedMetrics)
        })
    })

    describe('conversionWindow', () => {
        it('defaults to 14 days', () => {
            expect(logic.values.conversionWindow).toEqual({
                funnelWindowInterval: 14,
                funnelWindowIntervalUnit: 'day',
            })
        })

        it('reflects query source settings', () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 3,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Week,
                },
            }
            logic.actions.updateQuerySource(query)

            expect(logic.values.conversionWindow).toEqual({
                funnelWindowInterval: 3,
                funnelWindowIntervalUnit: 'week',
            })
        })

        it('draft interval defaults to null before any edits', () => {
            expect(logic.values.conversionWindowInterval).toBeNull()
            expect(logic.values.conversionWindowUnit).toBeNull()
        })

        it('setConversionWindowInterval updates the draft value', () => {
            logic.actions.setConversionWindowInterval(21)
            expect(logic.values.conversionWindowInterval).toBe(21)
        })

        it('setConversionWindowUnit updates the draft unit', () => {
            logic.actions.setConversionWindowUnit(FunnelConversionWindowTimeUnit.Hour)
            expect(logic.values.conversionWindowUnit).toBe(FunnelConversionWindowTimeUnit.Hour)
        })

        it('commitConversionWindow resets to saved value when interval is empty', async () => {
            logic.actions.setConversionWindowInterval(0)
            logic.actions.commitConversionWindow()

            await expectLogic(logic)
                .toDispatchActions(['commitConversionWindow', 'setConversionWindowInterval'])
                .toMatchValues({ conversionWindowInterval: 14 })
        })

        it('commitConversionWindow clamps values to bounds', () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }
            logic.actions.updateQuerySource(query)

            logic.actions.setConversionWindowInterval(9999)
            logic.actions.commitConversionWindow()
            expect(logic.values.conversionWindowInterval).toBe(365)

            logic.actions.setConversionWindowInterval(-5)
            logic.actions.commitConversionWindow()
            expect(logic.values.conversionWindowInterval).toBe(1)
        })

        it('commitConversionWindow calls updateInsightFilter when interval changed', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }
            logic.actions.updateQuerySource(query)

            logic.actions.setConversionWindowInterval(21)
            logic.actions.commitConversionWindow()

            await expectLogic(logic).toDispatchActions(['commitConversionWindow', 'updateInsightFilter'])
        })

        it('commitConversionWindow calls updateInsightFilter when only unit changed', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }
            logic.actions.updateQuerySource(query)

            logic.actions.setConversionWindowUnit(FunnelConversionWindowTimeUnit.Hour)
            logic.actions.commitConversionWindow()

            await expectLogic(logic).toDispatchActions(['commitConversionWindow', 'updateInsightFilter'])
        })

        it('commitConversionWindow does not call updateInsightFilter when value unchanged', async () => {
            const query: FunnelsQuery = {
                kind: NodeKind.FunnelsQuery,
                series: [],
                funnelsFilter: {
                    funnelWindowInterval: 14,
                    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                },
            }
            await expectLogic(logic, () => {
                logic.actions.updateQuerySource(query)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setConversionWindowInterval(14)
                logic.actions.commitConversionWindow()
            }).toNotHaveDispatchedActions(['updateInsightFilter'])
        })
    })

    describe('incompletenessOffsetFromEnd', () => {
        beforeAll(() => {
            const lastResponseDay = funnelResultTrends.result[0].days.slice(-1)[0]
            timekeeper.freeze(new Date(lastResponseDay))
        })

        afterAll(() => {
            timekeeper.reset()
        })

        it.each([
            ['defaults (14 day window)', undefined, -7],
            [
                '2 day conversion window',
                { funnelWindowInterval: 2, funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day },
                -3,
            ],
        ])('with %s returns correct offset', (_, funnelsFilter, expectedOffset) => {
            builtDataNodeLogic.actions.loadDataSuccess({
                filters: { insight: InsightType.FUNNELS },
                result: funnelResultTrends.result,
            })
            if (funnelsFilter) {
                const query: FunnelsQuery = {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter,
                }
                logic.actions.updateQuerySource(query)
            }

            expect(logic.values.incompletenessOffsetFromEnd).toBe(expectedOffset)
        })
    })
})
