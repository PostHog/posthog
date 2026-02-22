import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from './dataVisualizationLogic'
import { COMPLETE_STATE, displayLogic } from './displayLogic'

const testUniqueKey = 'testDisplayLogicKey'

const initialQuery: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: `select timestamp::date as date, count() as total_count from events group by 1`,
    },
    tableSettings: {
        columns: [
            { column: 'date', settings: { formatting: { prefix: '', suffix: '' } } },
            { column: 'total_count', settings: { formatting: { prefix: '', suffix: '' } } },
        ],
        conditionalFormatting: [],
    },
    chartSettings: { goalLines: undefined },
}

let globalQuery: DataVisualizationNode = { ...initialQuery }

const dummyDataVisualizationLogicProps: DataVisualizationLogicProps = {
    key: testUniqueKey,
    query: globalQuery,
    setQuery: (setter) => {
        globalQuery = setter(globalQuery)
        dummyDataVisualizationLogicProps.query = globalQuery
        dataVisualizationLogic.build(dummyDataVisualizationLogicProps)
    },
    editMode: false,
    dataNodeCollectionId: 'test-display-logic',
}

describe('displayLogic', () => {
    let logic: ReturnType<typeof displayLogic.build>
    let builtDataVizLogic: ReturnType<typeof dataVisualizationLogic.build>
    let builtDataNodeLogic: ReturnType<typeof dataNodeLogic.build>

    beforeEach(() => {
        initKeaTests()

        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            value: jest.fn().mockImplementation((query) => ({
                matches: false,
                media: query,
                onchange: null,
                addEventListener: jest.fn(),
                removeEventListener: jest.fn(),
                addListener: jest.fn(),
                removeListener: jest.fn(),
                dispatchEvent: jest.fn(),
            })),
        })

        featureFlagLogic.mount()
        globalQuery = {
            ...initialQuery,
            chartSettings: { goalLines: undefined },
        }
        dummyDataVisualizationLogicProps.query = globalQuery
        builtDataVizLogic = dataVisualizationLogic(dummyDataVisualizationLogicProps)
        builtDataVizLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        builtDataVizLogic?.unmount()
        builtDataNodeLogic?.unmount()
    })

    function setupDataWithDates(dates: string[]): void {
        if (!builtDataNodeLogic) {
            builtDataNodeLogic = dataNodeLogic({
                key: testUniqueKey,
                query: globalQuery.source,
            })
            builtDataNodeLogic.mount()
        }
        builtDataNodeLogic.actions.setResponse({
            results: dates.map((date, i) => [date, i * 10]),
            columns: ['date', 'total_count'],
            types: [
                ['date', 'String'],
                ['total_count', 'UInt64'],
            ],
        })
        builtDataVizLogic.actions.updateXSeries('date')
        builtDataVizLogic.actions.addYSeries('total_count')
    }

    describe('incompleteState selector', () => {
        beforeEach(() => {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2024-06-15T12:00:00Z'))
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('returns complete state for bar chart visualization', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            setupDataWithDates(['2024-06-14', '2024-06-15'])
            builtDataVizLogic.actions.setVisualizationType(ChartDisplayType.ActionsBar)

            await expectLogic(logic).toMatchValues({
                incompleteState: COMPLETE_STATE,
            })
        })

        it('returns complete state for stacked bar chart visualization', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            setupDataWithDates(['2024-06-14', '2024-06-15'])
            builtDataVizLogic.actions.setVisualizationType(ChartDisplayType.ActionsStackedBar)

            await expectLogic(logic).toMatchValues({
                incompleteState: COMPLETE_STATE,
            })
        })

        it('returns complete state when no xData', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                incompleteState: COMPLETE_STATE,
            })
        })

        it('returns complete state when all dates are in the past', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            setupDataWithDates(['2024-06-01', '2024-06-02', '2024-06-03'])
            builtDataVizLogic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)

            await expectLogic(logic).toMatchValues({
                incompleteState: COMPLETE_STATE,
            })
        })

        it.each([
            [
                'dashed (default)',
                undefined,
                { incompleteFrom: 2, incompleteTo: 2, trimCount: 0, shouldHide: false, shouldDash: true },
            ],
            [
                'dashed (explicit)',
                'dashed' as const,
                { incompleteFrom: 2, incompleteTo: 2, trimCount: 0, shouldHide: false, shouldDash: true },
            ],
            [
                'solid',
                'solid' as const,
                { incompleteFrom: 2, incompleteTo: 2, trimCount: 0, shouldHide: false, shouldDash: false },
            ],
            [
                'hidden',
                'hidden' as const,
                { incompleteFrom: 2, incompleteTo: 2, trimCount: 1, shouldHide: true, shouldDash: false },
            ],
        ])('computes incomplete range with mode=%s', async (_name, mode, expected) => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            setupDataWithDates(['2024-06-13', '2024-06-14', '2024-06-15'])
            builtDataVizLogic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)
            if (mode) {
                builtDataVizLogic.actions.updateChartSettings({ incompletePeriodDisplay: mode })
            }

            await expectLogic(logic).toMatchValues({
                incompleteState: expected,
            })
        })

        it('handles multiple incomplete periods in hidden mode', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            setupDataWithDates(['2024-06-12', '2024-06-13', '2024-06-14', '2024-06-15', '2024-06-16'])
            builtDataVizLogic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)
            builtDataVizLogic.actions.updateChartSettings({ incompletePeriodDisplay: 'hidden' })

            await expectLogic(logic).toMatchValues({
                incompleteState: {
                    incompleteFrom: 3,
                    incompleteTo: 4,
                    trimCount: 2,
                    shouldHide: true,
                    shouldDash: false,
                },
            })
        })

        it('handles descending date order', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            setupDataWithDates(['2024-06-15', '2024-06-14', '2024-06-13'])
            builtDataVizLogic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)

            await expectLogic(logic).toMatchValues({
                incompleteState: {
                    incompleteFrom: 0,
                    incompleteTo: 0,
                    trimCount: 0,
                    shouldHide: false,
                    shouldDash: true,
                },
            })
        })
    })

    describe('goalLines', () => {
        it('initializes with empty goal lines', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                goalLines: [],
            })
        })

        it('loads goal lines from chart settings on mount', async () => {
            const goalLines = [
                { label: 'Target', value: 100, displayLabel: true },
                { label: 'Minimum', value: 50, displayLabel: false },
            ]

            builtDataVizLogic?.unmount()

            globalQuery = {
                ...initialQuery,
                chartSettings: { goalLines },
            }
            dummyDataVisualizationLogicProps.query = globalQuery
            builtDataVizLogic = dataVisualizationLogic(dummyDataVisualizationLogicProps)
            builtDataVizLogic.mount()

            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                goalLines,
            })
        })

        it('adds a goal line', async () => {
            builtDataVizLogic?.unmount()
            globalQuery = { ...initialQuery }
            dummyDataVisualizationLogicProps.query = globalQuery
            builtDataVizLogic = dataVisualizationLogic(dummyDataVisualizationLogicProps)
            builtDataVizLogic.mount()

            setupDataWithDates(['2024-06-01', '2024-06-02', '2024-06-03'])

            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            logic.actions.addGoalLine()

            await expectLogic(logic).toMatchValues({
                goalLines: [
                    {
                        label: 'Q4 Goal',
                        value: 10,
                        displayLabel: true,
                    },
                ],
            })
        })

        it('updates a goal line', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            logic.actions.setGoalLines([{ label: 'Original', value: 100, displayLabel: true }])
            logic.actions.updateGoalLine(0, 'label', 'Updated Goal')

            await expectLogic(logic).toMatchValues({
                goalLines: [{ label: 'Updated Goal', value: 100, displayLabel: true }],
            })
        })

        it('removes a goal line', async () => {
            logic = displayLogic({ key: testUniqueKey })
            logic.mount()

            logic.actions.setGoalLines([
                { label: 'Goal 1', value: 100, displayLabel: true },
                { label: 'Goal 2', value: 200, displayLabel: false },
            ])
            logic.actions.removeGoalLine(0)

            await expectLogic(logic).toMatchValues({
                goalLines: [{ label: 'Goal 2', value: 200, displayLabel: false }],
            })
        })
    })
})
