import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { hasRecentAIEvents } from '../utils/aiEvents'
import { clustersSetupLogic } from './clustersSetupLogic'

jest.mock('../utils/aiEvents', () => ({ hasRecentAIEvents: jest.fn() }))

const mockHasRecentAIEvents = hasRecentAIEvents as jest.MockedFunction<typeof hasRecentAIEvents>

// Guards the three-way mapping into the app-wide setup-status layer: if it breaks,
// the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('clustersSetupLogic', () => {
    let querySpy: jest.SpyInstance

    beforeEach(() => {
        jest.clearAllMocks()
        querySpy = jest.spyOn(api, 'queryHogQL')
        initKeaTests()
    })

    afterEach(() => {
        querySpy.mockRestore()
    })

    it.each([
        [1, false, 'has-data'],
        [0, true, 'waiting-for-data'],
        [0, false, 'needs-setup'],
        [0, null, 'unknown'],
    ])('pushes %i runs and AI events=%s as status %s', async (runRows, hasAIEvents, expected) => {
        querySpy.mockResolvedValue({ results: Array.from({ length: runRows }, () => [1]) })
        mockHasRecentAIEvents.mockResolvedValue(hasAIEvents)
        const logic = clustersSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LLM_CLUSTERS }).values.status).toBe(expected)
    })

    it.each([
        [false, 'needs-setup'],
        [true, 'waiting-for-data'],
    ] as const)(
        'preserves the setup screen through a failed check with AI events=%s (%s)',
        async (hasAIEvents, expected) => {
            querySpy.mockResolvedValue({ results: [] })
            mockHasRecentAIEvents.mockResolvedValue(hasAIEvents)
            const logic = clustersSetupLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const setupStatus = productSetupStatusLogic({ productKey: ProductKey.LLM_CLUSTERS })
            expect(setupStatus.values.status).toBe(expected)

            mockHasRecentAIEvents.mockResolvedValue(null)
            logic.actions.detectStatus()
            await expectLogic(logic).toFinishAllListeners()
            expect(setupStatus.values.status).toBe(expected)

            mockHasRecentAIEvents.mockResolvedValue(hasAIEvents)
            logic.actions.detectStatus()
            await expectLogic(logic).toFinishAllListeners()
            expect(setupStatus.values.status).toBe(expected)

            querySpy.mockResolvedValue({ results: [[1]] })
            logic.actions.detectStatus()
            await expectLogic(logic).toFinishAllListeners()
            expect(setupStatus.values.status).toBe('has-data')
        }
    )
})
