import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { DataVisualizationLogicProps, dataVisualizationLogic } from './dataVisualizationLogic'

const testUniqueKey = 'testUniqueKey'

const initialQuery: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: `select event, count() as count_a, sum(1) as count_b from events group by 1`,
    },
    chartSettings: {
        yAxis: [
            {
                column: 'count_a',
                settings: {
                    formatting: { prefix: 'A-', suffix: '' },
                    display: { label: 'Series A' },
                },
            },
            {
                column: 'count_b',
                settings: {
                    formatting: { prefix: 'B-', suffix: '' },
                    display: { label: 'Series B' },
                },
            },
        ],
    },
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
    dataNodeCollectionId: 'new-test-SQL',
}

describe('dataVisualizationLogic', () => {
    let builtDataVizLogic: ReturnType<typeof dataVisualizationLogic.build>

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

        globalQuery = JSON.parse(JSON.stringify(initialQuery))
        dummyDataVisualizationLogicProps.query = globalQuery

        builtDataVizLogic = dataVisualizationLogic(dummyDataVisualizationLogicProps)
        builtDataVizLogic.mount()
        builtDataVizLogic.actions._setQuery(globalQuery)
    })

    afterEach(() => {
        builtDataVizLogic?.unmount()
    })

    describe('updateSeriesIndex', () => {
        it('does not mutate settings of other series when updating one series', async () => {
            await expectLogic(builtDataVizLogic).toMatchValues({
                selectedYAxis: [
                    {
                        name: 'count_a',
                        settings: {
                            formatting: { prefix: 'A-', suffix: '' },
                            display: { label: 'Series A' },
                        },
                    },
                    {
                        name: 'count_b',
                        settings: {
                            formatting: { prefix: 'B-', suffix: '' },
                            display: { label: 'Series B' },
                        },
                    },
                ],
            })

            const series0SettingsBefore = builtDataVizLogic.values.selectedYAxis?.[0]?.settings
            const series0SettingsBeforeCopy = JSON.parse(JSON.stringify(series0SettingsBefore))

            builtDataVizLogic.actions.updateSeriesIndex(1, 'count_b', {
                display: { label: 'Updated Series B' },
            })

            await expectLogic(builtDataVizLogic).toMatchValues({
                selectedYAxis: [
                    {
                        name: 'count_a',
                        settings: {
                            formatting: { prefix: 'A-', suffix: '' },
                            display: { label: 'Series A' },
                        },
                    },
                    {
                        name: 'count_b',
                        settings: {
                            formatting: { prefix: 'B-', suffix: '' },
                            display: { label: 'Updated Series B' },
                        },
                    },
                ],
            })

            expect(builtDataVizLogic.values.selectedYAxis?.[0]?.settings).toEqual(series0SettingsBeforeCopy)
        })

        it('creates new settings objects on update to ensure immutability', async () => {
            const series1SettingsBefore = builtDataVizLogic.values.selectedYAxis?.[1]?.settings

            builtDataVizLogic.actions.updateSeriesIndex(1, 'count_b', {
                display: { label: 'Updated Series B' },
            })

            const series1SettingsAfter = builtDataVizLogic.values.selectedYAxis?.[1]?.settings

            expect(series1SettingsAfter).not.toBe(series1SettingsBefore)
            expect(series1SettingsAfter?.display).not.toBe(series1SettingsBefore?.display)
        })

        it('preserves existing settings when updating partial settings', async () => {
            builtDataVizLogic.actions.updateSeriesIndex(0, 'count_a', {
                display: { color: 'red' },
            })

            await expectLogic(builtDataVizLogic).toMatchValues({
                selectedYAxis: [
                    {
                        name: 'count_a',
                        settings: {
                            formatting: { prefix: 'A-', suffix: '' },
                            display: { label: 'Series A', color: 'red' },
                        },
                    },
                    {
                        name: 'count_b',
                        settings: {
                            formatting: { prefix: 'B-', suffix: '' },
                            display: { label: 'Series B' },
                        },
                    },
                ],
            })
        })
    })
})
