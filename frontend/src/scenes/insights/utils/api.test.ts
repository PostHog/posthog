import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightModel } from '~/types'

import * as dashboardsApi from 'products/dashboards/frontend/generated/api'

import { insightsApi } from './api'

describe('insightsApi.create', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.insights, 'create').mockResolvedValue({ id: 12, dashboard_tiles: [] } as unknown as InsightModel)
        jest.spyOn(api.insights, 'update').mockResolvedValue({} as InsightModel)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('places the new insight on each dashboard in order, without sending dashboards', async () => {
        jest.spyOn(dashboardsApi, 'dashboardsAddInsightCreate').mockImplementation(async (_projectId, dashboardId) => ({
            id: 100 + dashboardId,
            dashboard_id: dashboardId,
        }))

        const insight = await insightsApi.create({ name: 'Weekly signups' }, [3, 4])

        expect(api.insights.create).toHaveBeenCalledWith({ name: 'Weekly signups' })
        expect((dashboardsApi.dashboardsAddInsightCreate as jest.Mock).mock.calls.map((call) => call.slice(1))).toEqual(
            [
                [3, { insight_id: 12 }],
                [4, { insight_id: 12 }],
            ]
        )
        expect(insight.dashboard_tiles).toEqual([
            { id: 103, dashboard_id: 3 },
            { id: 104, dashboard_id: 4 },
        ])
        expect(api.insights.update).not.toHaveBeenCalled()
    })

    const promql = { kind: NodeKind.MetricsQuery, clauses: [], language: 'promql', promql: 'up{job=~"$job"}' }
    const hogql = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select {variables.v}', variables: { v: { code_name: 'v' } } },
    }

    it.each([
        [
            'drops the variable values of a metrics query',
            { ...promql, variables: { job: { values: ['api'] } } },
            promql,
        ],
        ['keeps the variables of a SQL insight', hogql, hogql],
    ])('%s', async (_name, query, sentQuery) => {
        await insightsApi.create({ name: 'Copy', query: query as InsightModel['query'] })

        expect(api.insights.create).toHaveBeenCalledWith({ name: 'Copy', query: sentQuery })
    })

    it('deletes the new insight again when a dashboard refuses it', async () => {
        const refusal = { status: 403, detail: "You don't have permission to add insights to this dashboard." }
        jest.spyOn(dashboardsApi, 'dashboardsAddInsightCreate').mockRejectedValue(refusal)

        await expect(insightsApi.create({ name: 'Weekly signups' }, [3])).rejects.toBe(refusal)

        expect(api.insights.update).toHaveBeenCalledWith(12, { deleted: true }, undefined)
    })
})
