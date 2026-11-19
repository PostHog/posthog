import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { clusteringConfigLogic } from '../clusters/clusteringConfigLogic'
import { llmAnalyticsClusteringConfigList } from '../generated/api'
import type { ClusteringConfigApi } from '../generated/api.schemas'
import { clustersSetupLogic } from './clustersSetupLogic'

jest.mock('../generated/api', () => ({ llmAnalyticsClusteringConfigList: jest.fn() }))

const mockConfig = jest.mocked(llmAnalyticsClusteringConfigList)
const config = (enabled: boolean): ClusteringConfigApi => ({
    enabled,
    event_filters: [],
    created_at: '',
    updated_at: '',
})

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
        jest.useRealTimers()
    })

    it.each([
        [1, true, 'has-data'],
        [1, false, 'has-data'],
        [0, true, 'waiting-for-data'],
        [0, false, 'needs-setup'],
    ] as const)('pushes %i runs and enabled=%s as status %s', async (runRows, enabled, expected) => {
        querySpy.mockResolvedValue({ results: Array.from({ length: runRows }, () => [1]) })
        mockConfig.mockResolvedValue(config(enabled))
        const logic = clustersSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LLM_CLUSTERS }).values.status).toBe(expected)
    })

    it('moves to the waiting state immediately after enabling without any runs', async () => {
        querySpy.mockResolvedValue({ results: [] })
        mockConfig.mockResolvedValue(config(false))
        const logic = clustersSetupLogic()
        logic.mount()
        clusteringConfigLogic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(clusteringConfigLogic).toFinishAllListeners()
        const setupStatus = productSetupStatusLogic({ productKey: ProductKey.LLM_CLUSTERS })
        expect(setupStatus.values.status).toBe('needs-setup')

        mockConfig.mockResolvedValue(config(true))
        clusteringConfigLogic.actions.saveEnabledSuccess(config(true))
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus.values.status).toBe('waiting-for-data')
    })

    it('automatically leaves the waiting state when the first run appears', async () => {
        jest.useFakeTimers()
        querySpy.mockResolvedValue({ results: [] })
        mockConfig.mockResolvedValue(config(true))
        const logic = clustersSetupLogic()
        logic.mount()
        try {
            await jest.advanceTimersByTimeAsync(0)
            const setupStatus = productSetupStatusLogic({ productKey: ProductKey.LLM_CLUSTERS })
            expect(setupStatus.values.status).toBe('waiting-for-data')

            querySpy.mockResolvedValue({ results: [[1]] })
            await jest.advanceTimersByTimeAsync(30000)
            expect(setupStatus.values.status).toBe('has-data')
        } finally {
            logic.unmount()
            jest.useRealTimers()
        }
    })

    it.each([
        [false, 'needs-setup'],
        [true, 'waiting-for-data'],
    ] as const)('preserves the setup screen through a failed check with enabled=%s (%s)', async (enabled, expected) => {
        querySpy.mockResolvedValue({ results: [] })
        mockConfig.mockResolvedValue(config(enabled))
        const logic = clustersSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const setupStatus = productSetupStatusLogic({ productKey: ProductKey.LLM_CLUSTERS })
        expect(setupStatus.values.status).toBe(expected)

        mockConfig.mockRejectedValue(new Error('Configuration unavailable'))
        logic.actions.detectStatus()
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus.values.status).toBe(expected)

        mockConfig.mockResolvedValue(config(enabled))
        logic.actions.detectStatus()
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus.values.status).toBe(expected)

        querySpy.mockResolvedValue({ results: [[1]] })
        mockConfig.mockResolvedValue(config(true))
        logic.actions.detectStatus()
        await expectLogic(logic).toFinishAllListeners()
        expect(setupStatus.values.status).toBe('has-data')
    })
})
