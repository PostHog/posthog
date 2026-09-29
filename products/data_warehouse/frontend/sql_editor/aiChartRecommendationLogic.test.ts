import { MOCK_DEFAULT_ORGANIZATION } from '~/lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { OutputTab, outputPaneLogic } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import * as queryApi from '~/queries/query'
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

    beforeEach(async () => {
        initKeaTests()
        decide = jest.spyOn(decisionsApi, 'mlInferenceDecisionsDecideCreate').mockResolvedValue(decision)
        featureFlagLogic.actions.setFeatureFlags([], {
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
            cachedResults: { columns: [], types: [], results: [] },
        }).mount()
        logic = aiChartRecommendationLogic({ visualizationProps, tabId: 'jev-test' })
        logic.mount()
        visualization = dataVisualizationLogic(visualizationProps)
        await expectLogic(preflightLogic).toFinishAllListeners()
        preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: false })
    })

    afterEach(() => {
        logic.unmount()
        unmountData()
        decide.mockRestore()
    })

    it.each(['production', 'local development'])(
        'selects axes, chart and split layout after a query completes in %s',
        async (environment) => {
            if (environment === 'local development') {
                featureFlagLogic.actions.setFeatureFlags([], {})
                preflightLogic.actions.loadPreflightSuccess({ ...preflightLogic.values.preflight!, is_debug: true })
            }
            await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
            expect(decide).toHaveBeenCalledTimes(1)
            expect(visualization.values.query.display).toBe(ChartDisplayType.ActionsBar)
            expect(visualization.values.selectedXAxis).toBe('category')
            expect(visualization.values.selectedYAxis?.map((axis) => axis?.name)).toEqual(['value'])
            expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Both)
            expect(logic.values.choosingChart).toBe(false)
        }
    )

    it.each(['consent', 'decisions service', 'manual chart'])(
        'keeps the existing behavior without %s eligibility',
        async (reason) => {
            if (reason === 'consent') {
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: false,
                })
            } else if (reason === 'decisions service') {
                featureFlagLogic.actions.setFeatureFlags([], {})
            } else {
                visualization.actions.setVisualizationType(ChartDisplayType.ActionsTable)
            }
            await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
            expect(decide).not.toHaveBeenCalled()
            expect(logic.values.choosingChart).toBe(false)
            expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Results)
        }
    )

    it('keeps heuristic axes and the current layout when inference fails', async () => {
        decide.mockRejectedValue(new Error('Unavailable'))
        await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
        expect(visualization.values.query.display).toBe(ChartDisplayType.Auto)
        expect(visualization.values.selectedXAxis).toBe('category')
        expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Results)
        expect(logic.values.choosingChart).toBe(false)
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

    it.each(['consent', 'axes', 'layout', 'query', 'skip', 'rerun'])(
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
            expect(logic.values.choosingChart).toBe(true)
            await requestStarted
            expect(decide).toHaveBeenCalled()
            expect(visualization.values.query.display).toBe(ChartDisplayType.Auto)
            expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Results)
            if (change === 'consent') {
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: false,
                })
            } else if (change === 'axes') {
                visualization.actions.updateXSeries('value')
            } else if (change === 'layout') {
                outputPaneLogic({ tabId: 'jev-test' }).actions.setActiveTab(OutputTab.Visualization)
            } else if (change === 'skip') {
                logic.actions.skipRecommendation()
                expect(logic.values.choosingChart).toBe(false)
                expect(decide.mock.calls[0][2].signal.aborted).toBe(true)
            } else if (change === 'rerun') {
                dataNodeLogic({
                    key: 'jev-test',
                    query: visualization.values.query.source,
                    doNotLoad: true,
                    cachedResults: { ...response, results: [] },
                })
                logic.actions.loadData()
                expect(logic.values.choosingChart).toBe(false)
                expect(decide.mock.calls[0][2].signal.aborted).toBe(true)
            } else {
                visualization.actions.setQuery((query) => ({
                    ...query,
                    source: { ...query.source, query: 'select something_else' },
                }))
            }
            await expectLogic(logic, () => resolve(decision)).toFinishAllListeners()
            expect(visualization.values.query.display).toBe(ChartDisplayType.Auto)
            expect(logic.values.choosingChart).toBe(false)
        }
    )

    it('can show results before the recommendation request starts', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadDataSuccess(response)
            expect(logic.values.choosingChart).toBe(true)
            logic.actions.skipRecommendation()
        }).toFinishAllListeners()
        expect(decide).not.toHaveBeenCalled()
        expect(logic.values.choosingChart).toBe(false)
        expect(outputPaneLogic({ tabId: 'jev-test' }).values.activeTab).toBe(OutputTab.Results)
    })

    it.each(['matching', 'different', 'missing', 'unknown'])(
        'starts selection before results and handles %s inferred columns',
        async (schema) => {
            const metadata = jest.spyOn(queryApi, 'performQuery').mockResolvedValue({
                isValid: true,
                errors: [],
                warnings: [],
                notices: [],
                output_columns:
                    schema === 'missing'
                        ? undefined
                        : [
                              { name: schema === 'different' ? 'other' : 'category', type: 'String' },
                              { name: 'value', type: schema === 'unknown' ? 'Nullable(Unknown)' : 'Int64' },
                          ],
            })
            try {
                const query = visualization.values.query
                visualization.actions._setQuery({ ...query, source: { kind: NodeKind.HogQLQuery, query: '' } })
                dataNodeLogic({
                    key: 'jev-test',
                    query: query.source,
                    cachedResults: { columns: [], types: [], results: [] },
                })
                await expectLogic(logic, () => {
                    logic.actions.loadData('force_async', undefined, {
                        ...query.source,
                        tags: { productKey: 'sql_editor' },
                    })
                    visualization.actions._setQuery(query)
                }).toFinishAllListeners()
                expect(metadata).toHaveBeenCalledWith(
                    expect.objectContaining({ includeOutputTypes: true, query: 'select category, value' }),
                    expect.objectContaining({ signal: expect.any(AbortSignal) })
                )
                if (schema === 'matching' || schema === 'different') {
                    await waitFor(() => expect(decide).toHaveBeenCalledTimes(1))
                    expect(JSON.parse(decide.mock.calls[0][1].state)).toMatchObject({
                        schema_only: true,
                        row_count: null,
                    })
                } else {
                    expect(decide).not.toHaveBeenCalled()
                }
                expect(logic.values.choosingChart).toBe(false)
                expect(visualization.values.query.display).toBe(ChartDisplayType.Auto)
                await expectLogic(logic, () => logic.actions.loadDataSuccess(response)).toFinishAllListeners()
                expect(decide).toHaveBeenCalledTimes(1)
                expect(visualization.values.query.display).toBe(
                    schema === 'different' ? ChartDisplayType.Auto : ChartDisplayType.ActionsBar
                )
            } finally {
                metadata.mockRestore()
            }
        }
    )

    it.each(['consent', 'query', 'skip'])(
        'does not send inferred columns to Jev after changing %s while metadata loads',
        async (change) => {
            let resolve!: (
                metadata: NonNullable<import('~/queries/schema/schema-general').HogQLMetadata['response']>
            ) => void
            const metadata = jest.spyOn(queryApi, 'performQuery').mockImplementation(
                () =>
                    new Promise((done) => {
                        resolve = done
                    })
            )
            try {
                dataNodeLogic({
                    key: 'jev-test',
                    query: visualization.values.query.source,
                    cachedResults: { columns: [], types: [], results: [] },
                })
                await expectLogic(logic, () => logic.actions.loadData()).toFinishAllListeners()
                if (change === 'consent') {
                    organizationLogic.actions.loadCurrentOrganizationSuccess({
                        ...MOCK_DEFAULT_ORGANIZATION,
                        is_ai_data_processing_approved: false,
                    })
                } else if (change === 'query') {
                    visualization.actions.setQuery((query) => ({
                        ...query,
                        source: { ...query.source, query: 'select something_else' },
                    }))
                } else {
                    logic.actions.skipRecommendation()
                }
                resolve({
                    isValid: true,
                    errors: [],
                    warnings: [],
                    notices: [],
                    output_columns: [{ name: 'value', type: 'Int64' }],
                })
                await metadata.mock.results[0].value
                expect(decide).not.toHaveBeenCalled()
            } finally {
                metadata.mockRestore()
            }
        }
    )
})
