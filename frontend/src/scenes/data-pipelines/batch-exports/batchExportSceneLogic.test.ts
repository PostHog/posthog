import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { batchExportSceneLogic } from './BatchExportScene'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

describe('batchExportSceneLogic', () => {
    let logic: ReturnType<typeof batchExportSceneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/batch_exports/test-id/': {
                    id: 'test-id',
                    team_id: 997,
                    name: 'Test Export',
                    destination: { type: 'S3', config: {} },
                    interval: 'hour',
                    paused: false,
                    model: 'events',
                    filters: [],
                },
                '/api/environments/:team_id/batch_exports/test/': { steps: [] },
            },
        })
        initKeaTests()
    })

    async function initLogic(): Promise<void> {
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = batchExportSceneLogic({ id: 'test-id', service: null })
        logic.mount()
    }

    it('defaults to configuration tab', async () => {
        await initLogic()

        expect(logic.values.currentTab).toBe('configuration')
    })

    it('switches tabs via setCurrentTab', async () => {
        await initLogic()

        logic.actions.setCurrentTab('runs')
        expect(logic.values.currentTab).toBe('runs')

        logic.actions.setCurrentTab('backfills')
        expect(logic.values.currentTab).toBe('backfills')

        logic.actions.setCurrentTab('logs')
        expect(logic.values.currentTab).toBe('logs')

        logic.actions.setCurrentTab('metrics')
        expect(logic.values.currentTab).toBe('metrics')
    })

    it('syncs tab to URL search params', async () => {
        await initLogic()

        logic.actions.setCurrentTab('runs')
        expect(router.values.searchParams).toEqual(expect.objectContaining({ tab: 'runs' }))

        logic.actions.setCurrentTab('backfills')
        expect(router.values.searchParams).toEqual(expect.objectContaining({ tab: 'backfills' }))
    })
})
