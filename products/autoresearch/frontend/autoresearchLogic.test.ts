import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { autoresearchLogic } from './autoresearchLogic'
import {
    autoresearchDestroy,
    autoresearchList,
    autoresearchPauseCreate,
    autoresearchResumeCreate,
} from './generated/api'
import { AutoresearchPipelineApi } from './generated/api.schemas'

jest.mock('./generated/api', () => ({
    autoresearchList: jest.fn(),
    autoresearchDestroy: jest.fn(),
    autoresearchPauseCreate: jest.fn(),
    autoresearchResumeCreate: jest.fn(),
}))

const mockList = autoresearchList as jest.Mock

type Settle = { resolve: (value: unknown) => void; reject: (reason: unknown) => void }

describe('autoresearchLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], { [FEATURE_FLAGS.AUTORESEARCH]: true })
    })

    function statusLogicValues(): string {
        return productSetupStatusLogic({ productKey: ProductKey.AUTORESEARCH }).values.status
    }

    it.each([
        [0, 'needs-setup'],
        [2, 'has-data'],
    ])('pushes the setup status for %i pipelines so the empty-state gate routes correctly', async (count, expected) => {
        mockList.mockResolvedValue({ results: Array.from({ length: count }, (_, i) => ({ id: String(i) })) })
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(statusLogicValues()).toBe(expected)
    })

    it('fails open to unknown when the list load fails with no earlier answer', async () => {
        mockList.mockRejectedValue(new Error('network down'))
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(statusLogicValues()).toBe('unknown')
        expect(logic.values.pipelinesLoadFailed).toBe(true)

        mockList.mockReturnValue(new Promise(() => {}))
        logic.actions.loadPipelines()
        expect(logic.values.pipelinesLoadFailed).toBe(false)
    })

    it('follows every page of the list', async () => {
        mockList
            .mockResolvedValueOnce({ results: [{ id: 'a' }, { id: 'b' }], next: 'page-2' })
            .mockResolvedValueOnce({ results: [{ id: 'c' }], next: null })
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pipelines.map((p) => p.id)).toEqual(['a', 'b', 'c'])
        expect(mockList).toHaveBeenLastCalledWith(expect.any(String), { offset: 2 })
    })

    it.each([
        ['succeeds', (settle: Settle) => settle.resolve({ results: [{ id: 'old' }], next: null })],
        ['fails', (settle: Settle) => settle.reject(new Error('network down'))],
    ])('keeps the newer list when an older load %s last', async (_, finishOlder) => {
        const settle = {} as Settle
        mockList
            .mockReturnValueOnce(
                new Promise((resolve, reject) => {
                    settle.resolve = resolve
                    settle.reject = reject
                })
            )
            .mockResolvedValueOnce({ results: [{ id: 'new' }], next: null })
        const logic = autoresearchLogic()
        logic.mount()
        logic.actions.loadPipelines()
        await expectLogic(logic).toDispatchActions(['loadPipelinesSuccess'])
        finishOlder(settle)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pipelines.map((p) => p.id)).toEqual(['new'])
        expect(logic.values.pipelinesLoadFailed).toBe(false)
    })

    it.each([
        ['deletePipeline', autoresearchDestroy],
        ['pausePipeline', autoresearchPauseCreate],
        ['resumePipeline', autoresearchResumeCreate],
    ] as const)('sends one %s request while the first is in flight', async (action, apiCall) => {
        mockList.mockResolvedValue({ results: [] })
        ;(apiCall as jest.Mock).mockReturnValue(new Promise(() => {}))
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const pipeline = { id: 'p1', name: 'Model' } as AutoresearchPipelineApi
        for (let i = 0; i < 2; i++) {
            if (action === 'deletePipeline') {
                logic.actions.deletePipeline(pipeline.id, pipeline.name)
            } else {
                logic.actions[action](pipeline)
            }
        }
        expect(apiCall).toHaveBeenCalledTimes(1)
    })

    it('does not load the list with the flag off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        router.actions.push(urls.autoresearch())
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).not.toHaveBeenCalled()
    })

    it('updates a row as soon as its pause succeeds', async () => {
        mockList.mockResolvedValueOnce({ results: [{ id: 'p1', name: 'Model', status: 'running' }], next: null })
        mockList.mockReturnValue(new Promise(() => {}))
        ;(autoresearchPauseCreate as jest.Mock).mockResolvedValue({ id: 'p1', name: 'Model', status: 'paused' })
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPipelinesSuccess'])
        logic.actions.pausePipeline(logic.values.pipelines[0])
        await expectLogic(logic).toDispatchActions(['pipelineUpdated'])
        expect(logic.values.pipelines[0].status).toBe('paused')
    })

    it('loads once when mounted on the list route', async () => {
        mockList.mockResolvedValue({ results: [] })
        router.actions.push(urls.autoresearch())
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenCalledTimes(1)
    })
})
