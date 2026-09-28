import { MOCK_DEFAULT_ORGANIZATION } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { OutputTab, outputPaneLogic } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import * as decisionsApi from 'products/ml_inference/frontend/generated/api'
import type { DecideResponseApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { aiChartRecommendationLogic } from './aiChartRecommendationLogic'

const response = {
    columns: ['category', 'value'],
    types: [
        ['category', 'String'],
        ['value', 'Int64'],
    ],
    results: [
        ['One', 10],
        ['Two', 20],
    ],
}
const decision: DecideResponseApi = {
    model: 'test',
    input_tokens: 1,
    latency_ms: 1,
    answers: Object.fromEntries(
        Object.entries({
            chart: ChartDisplayType.ActionsBar,
            layout: OutputTab.Both,
            x: 'c0',
            value: 'c1',
            dimension: 'none',
        }).map(([key, choice]) => [
            key,
            { type: 'choice', choice, probability: null, score: null, confidence: 1, probabilities: {} },
        ])
    ),
}

describe('aiChartRecommendationLogic', () => {
    let logic: ReturnType<typeof aiChartRecommendationLogic.build>
    let visualization: ReturnType<typeof dataVisualizationLogic.build>
    let decide: jest.SpyInstance
    let unmountData: () => void

    beforeEach(() => {
        initKeaTests()
        decide = jest.spyOn(decisionsApi, 'mlInferenceDecisionsDecideCreate').mockResolvedValue(decision)
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.JEV_CHART_AUTODETECTION]: true,
            [FEATURE_FLAGS.ML_INFERENCE_DECISIONS]: true,
        })
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: true,
        })
        const visualizationProps = {
            key: 'jev-test',
            dataNodeCollectionId: 'jev-test',
            query: {
                kind: NodeKind.DataVisualizationNode as const,
                display: ChartDisplayType.Auto,
                source: { kind: NodeKind.HogQLQuery as const, query: 'select category, value' },
            },
        }
        unmountData = dataNodeLogic({
            key: visualizationProps.key,
            query: visualizationProps.query.source,
            autoLoad: false,
            doNotLoad: true,
        }).mount()
        logic = aiChartRecommendationLogic({ visualizationProps, tabId: 'jev-test' })
        logic.mount()
        visualization = dataVisualizationLogic(visualizationProps)
    })

    afterEach(() => {
        logic.unmount()
        unmountData()
        decide.mockRestore()
    })

    it('selects axes, chart and split layout after a query completes', async () => {
        await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
        expect(decide).toHaveBeenCalledTimes(1)
        expect(visualization.values.query.display).toBe(ChartDisplayType.ActionsBar)
        expect(visualization.values.selectedXAxis).toBe('category')
        expect(visualization.values.selectedYAxis?.map((axis) => axis?.name)).toEqual(['value'])
        expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Both)
    })

    it.each(['consent', 'flag', 'manual chart'])(
        'keeps the existing behavior without %s eligibility',
        async (reason) => {
            if (reason === 'consent') {
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: false,
                })
            } else if (reason === 'flag') {
                featureFlagLogic.actions.setFeatureFlags([], {})
            } else {
                visualization.actions.setVisualizationType(ChartDisplayType.ActionsTable)
            }
            await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
            expect(decide).not.toHaveBeenCalled()
            expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Results)
        }
    )

    it('keeps heuristic axes and the current layout when inference fails', async () => {
        decide.mockRejectedValue(new Error('Unavailable'))
        await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
        expect(visualization.values.query.display).toBe(ChartDisplayType.Auto)
        expect(visualization.values.selectedXAxis).toBe('category')
        expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Results)
    })

    it('returns to the existing auto behavior on the next run when consent is revoked', async () => {
        await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
        expect(visualization.values.query.display).toBe(ChartDisplayType.ActionsBar)
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        dataNodeLogic({
            key: 'jev-test',
            query: visualization.values.query.source,
            doNotLoad: true,
            cachedResults: response,
        })
        await expectLogic(logic, () => logic.actions.loadData()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
        expect(decide).toHaveBeenCalledTimes(1)
        expect(visualization.values.query.display).toBe(ChartDisplayType.Auto)
        expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Results)
    })

    it.each(['consent', 'axes', 'layout', 'query'])(
        'ignores an in-flight decision after changing %s',
        async (change) => {
            let resolve!: (result: DecideResponseApi) => void
            let started!: () => void
            const requestStarted = new Promise<void>((done) => {
                started = done
            })
            decide.mockImplementation(() => {
                started()
                return new Promise<DecideResponseApi>((done) => {
                    resolve = done
                })
            })
            logic.actions.loadDataSuccess(response)
            await requestStarted
            expect(decide).toHaveBeenCalled()
            if (change === 'consent') {
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: false,
                })
            } else if (change === 'axes') {
                visualization.actions.updateXSeries('value')
            } else if (change === 'layout') {
                outputPaneLogic({ tabId: 'jev-test' }).actions.setActiveTab(OutputTab.Visualization)
            } else {
                visualization.actions.setQuery((query) => ({
                    ...query,
                    source: { ...query.source, query: 'select something_else' },
                }))
            }
            await expectLogic(logic, () => resolve(decision)).toFinishAllListeners()
            expect(visualization.values.query.display).toBe(ChartDisplayType.Auto)
        }
    )
})
