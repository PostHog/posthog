import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataDeletionLogic } from './dataDeletionLogic'

describe('dataDeletionLogic', () => {
    let logic: ReturnType<typeof dataDeletionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_deletion_requests/': { results: [] },
            },
            post: {
                '/api/environments/:team_id/data_deletion_requests/preview/': {
                    count: 42,
                    min_timestamp: '2026-01-01T00:00:00Z',
                    max_timestamp: '2026-01-02T00:00:00Z',
                    rows: [
                        {
                            uuid: 'abc',
                            event: '$pageview',
                            timestamp: '2026-01-01T12:00:00Z',
                            distinct_id: 'user-1',
                            properties: '{}',
                        },
                    ],
                    limit: 3000,
                    truncated: false,
                },
            },
        })
        initKeaTests()
        logic = dataDeletionLogic()
        logic.mount()
    })

    it('starts on the new request tab with empty list', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.activeTab).toBe('new')
        expect(logic.values.deletionRequests).toEqual([])
    })

    it('marks form as scoped when event, start time, and predicate criteria line up', () => {
        expect(logic.values.previewScoped).toBe(false)
        logic.actions.setNewRequestValue('start_time', '2026-01-01T00:00:00Z')
        expect(logic.values.previewScoped).toBe(false)
        logic.actions.setNewRequestValue('events', ['$pageview'])
        expect(logic.values.previewScoped).toBe(true)
    })

    it('does not run a preview until runPreview is dispatched', async () => {
        logic.actions.setNewRequestValue('start_time', '2026-01-01T00:00:00Z')
        logic.actions.setNewRequestValue('events', ['$pageview'])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.preview).toBeNull()
        expect(logic.values.previewIsFresh).toBe(false)

        logic.actions.runPreview()
        await expectLogic(logic).toDispatchActions(['refreshPreview', 'refreshPreviewSuccess']).toFinishAllListeners()
        expect(logic.values.preview?.count).toBe(42)
        expect(logic.values.previewIsFresh).toBe(true)
    })

    it('marks preview as stale after the form changes', async () => {
        logic.actions.setNewRequestValue('start_time', '2026-01-01T00:00:00Z')
        logic.actions.setNewRequestValue('events', ['$pageview'])
        logic.actions.runPreview()
        await expectLogic(logic).toDispatchActions(['refreshPreviewSuccess']).toFinishAllListeners()
        expect(logic.values.previewIsFresh).toBe(true)

        logic.actions.setNewRequestValue('events', ['$pageview', '$autocapture'])
        expect(logic.values.preview?.count).toBe(42)
        expect(logic.values.previewIsFresh).toBe(false)
    })

    it('flags property_removal as missing properties', () => {
        logic.actions.setNewRequestValue('request_type', 'property_removal')
        logic.actions.setNewRequestValue('start_time', '2026-01-01T00:00:00Z')
        expect(logic.values.previewScoped).toBe(false)
        logic.actions.setNewRequestValue('properties', ['$browser'])
        expect(logic.values.previewScoped).toBe(true)
    })

    it('materializes "through now" end_time into the form when preview runs', async () => {
        expect(logic.values.newRequest.end_time_through_now).toBe(true)
        expect(logic.values.newRequest.end_time).toBeNull()

        logic.actions.setNewRequestValue('start_time', '2026-01-01T00:00:00Z')
        logic.actions.setNewRequestValue('events', ['$pageview'])
        logic.actions.runPreview()
        await expectLogic(logic).toDispatchActions(['refreshPreviewSuccess']).toFinishAllListeners()

        expect(logic.values.newRequest.end_time_through_now).toBe(false)
        expect(logic.values.newRequest.end_time).not.toBeNull()
        expect(logic.values.previewIsFresh).toBe(true)
    })
})
