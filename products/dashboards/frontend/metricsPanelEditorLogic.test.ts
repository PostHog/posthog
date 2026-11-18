import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsPanelEditorLogic } from './metricsPanelEditorLogic'

const savedQuery = {
    kind: NodeKind.MetricsQuery,
    clauses: [{ name: 'a', metricName: 'http_requests_total' }],
    dateRange: { date_from: '-24h' },
}
const original = {
    id: 101,
    short_id: 'requests1',
    name: 'Requests',
    query: savedQuery,
    user_access_level: 'editor',
    dashboard_tiles: [
        { id: 1, dashboard_id: 5 },
        { id: 2, dashboard_id: 6 },
        { id: 3, dashboard_id: 6 },
        { id: 4, dashboard_id: 7, deleted: true },
    ],
}

describe('metricsPanelEditorLogic', () => {
    let updates: unknown[]
    const onSaved = jest.fn()
    const onClose = jest.fn()

    beforeEach(() => {
        updates = []
        onSaved.mockReset()
        onClose.mockReset()
        useMocks({
            get: { '/api/environments/:team_id/insights/101/': original },
            patch: {
                '/api/environments/:team_id/insights/101/': async ({ request }) => {
                    updates.push(await request.json())
                    return [200, original]
                },
            },
        })
        initKeaTests()
    })

    function mountEditor(): ReturnType<typeof metricsPanelEditorLogic.build> {
        const logic = metricsPanelEditorLogic({
            projectId: 2,
            insightId: 101,
            filtersOverride: { date_from: '-1h' },
            onSaved,
            onClose,
        })
        logic.mount()
        return logic
    }

    it('saves the original query without baking dashboard preview filters into the insight', async () => {
        const logic = mountEditor()
        await expectLogic(logic).toDispatchActions(['loadInsightSuccess'])
        expect(logic.values.query).toEqual(savedQuery)
        expect(logic.values.dirty).toBe(false)
        expect(logic.values.dashboardCount).toBe(2)

        await expectLogic(logic, () => {
            logic.actions.setName('Request volume')
            logic.actions.save()
            logic.actions.save()
        }).toFinishAllListeners()

        expect(updates).toEqual([{ name: 'Request volume', query: savedQuery }])
        expect(onSaved).toHaveBeenCalledTimes(1)
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it.each(['viewer', 'none'])('does not save with %s access', async (user_access_level) => {
        useMocks({ get: { '/api/environments/:team_id/insights/101/': { ...original, user_access_level } } })
        const logic = mountEditor()
        await expectLogic(logic).toDispatchActions(['loadInsightSuccess'])
        await expectLogic(logic, () => {
            logic.actions.setName('Edited name')
            logic.actions.save()
        }).toFinishAllListeners()

        expect(updates).toEqual([])
        expect(onClose).not.toHaveBeenCalled()
        expect(logic.values.saving).toBe(false)
    })

    it('keeps the draft and allows a retry after a refused save', async () => {
        useMocks({
            patch: { '/api/environments/:team_id/insights/101/': [403, { detail: 'Edit access was removed' }] },
        })
        const logic = mountEditor()
        await expectLogic(logic).toDispatchActions(['loadInsightSuccess'])
        await expectLogic(logic, () => {
            logic.actions.setName('Keep this draft')
            logic.actions.save()
        }).toFinishAllListeners()

        expect(logic.values.name).toBe('Keep this draft')
        expect(logic.values.error).toBe('Edit access was removed')
        expect(logic.values.saving).toBe(false)
        expect(onSaved).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })
})
