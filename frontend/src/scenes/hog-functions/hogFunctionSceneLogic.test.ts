import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFunctions: {
        get: jest.fn(),
        getTemplate: jest.fn(),
        update: jest.fn(),
        create: jest.fn(),
    },
}))

const mockApi = api.hogFunctions as jest.Mocked<typeof api.hogFunctions>

const LOG_TRANSFORMATION: HogFunctionType = {
    id: 'fn-1',
    type: 'transformation_log',
    name: 'Scrub PII',
    description: '',
    created_at: '2026-01-01',
    created_by: null,
    updated_at: '2026-01-01',
    enabled: true,
    hog: 'return record',
    inputs_schema: [],
    inputs: {},
    filters: null,
    icon_url: null,
    template: null,
    status: { state: 1, tokens: 0 } as any,
} as unknown as HogFunctionType

describe('hogFunctionSceneLogic', () => {
    it('falls back from a deep-linked tab the loaded type never renders', async () => {
        // `type` arrives after the URL fires, so ?tab=invocations on a log
        // transformation used to stick and LemonTabs rendered no active content.
        initKeaTests()
        // Required lazily: the scene's component import chain reads the app context
        // at module scope, which initKeaTests only provides at test time.
        const { hogFunctionSceneLogic } = require('./HogFunctionScene')
        mockApi.get.mockResolvedValue(LOG_TRANSFORMATION)

        router.actions.push(urls.hogFunction('fn-1'), { tab: 'invocations' })
        const logic = hogFunctionSceneLogic({ id: 'fn-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadHogFunctionSuccess'])
        expect(logic.values.currentTab).toBe('configuration')
    })
})
