import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

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
    autoresearchTrainCreate,
    autoresearchValidateCreate,
} from './generated/api'
import { AutoresearchPipelineApi } from './generated/api.schemas'

jest.mock('./generated/api', () => ({
    autoresearchList: jest.fn(),
    autoresearchDestroy: jest.fn(),
    autoresearchPauseCreate: jest.fn(),
    autoresearchResumeCreate: jest.fn(),
    autoresearchTrainCreate: jest.fn(),
    autoresearchValidateCreate: jest.fn(),
}))

const mockList = autoresearchList as jest.Mock
const mockTrain = autoresearchTrainCreate as jest.Mock
const mockValidate = autoresearchValidateCreate as jest.Mock

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
        expect(logic.values.pipelines).toEqual([])

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
        ['startTraining', autoresearchTrainCreate],
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

    it('waits for the flag before it loads the list', async () => {
        mockList.mockResolvedValue({ results: [], next: null })
        featureFlagLogic.actions.setFeatureFlags([], {})
        router.actions.push(urls.autoresearch())
        const logic = autoresearchLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AUTORESEARCH], { [FEATURE_FLAGS.AUTORESEARCH]: true })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenCalledTimes(1)
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

    it.each([
        ['a draft that never trained and passes the check', 'draft', 0, { can_proceed: true, error: null }, 1, false],
        [
            'a draft that never trained and fails the check',
            'draft',
            0,
            { can_proceed: false, error: 'Validation ran out of time', error_code: 'too_expensive' },
            0,
            true,
        ],
        ['a draft that trained before', 'draft', 1, null, 1, false],
        ['a running model', 'running', 3, null, 1, false],
    ] as const)(
        'checks %s before Start training, and asks before a run the check failed',
        async (_, status, trainingRunCount, validation, trainsBeforeConfirm, asks) => {
            mockList.mockResolvedValue({ results: [] })
            mockValidate.mockResolvedValue({ warnings: [], error_code: null, ...validation })
            mockTrain.mockResolvedValue({ id: 'run-1' })
            const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            const logic = autoresearchLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const pipeline = {
                id: 'p1',
                name: 'Model',
                status,
                training_run_count: trainingRunCount,
            } as unknown as AutoresearchPipelineApi

            logic.actions.requestTraining(pipeline)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockValidate).toHaveBeenCalledTimes(validation ? 1 : 0)
            expect(mockTrain).toHaveBeenCalledTimes(trainsBeforeConfirm)
            expect(openDialog).toHaveBeenCalledTimes(asks ? 1 : 0)

            // Confirming the dialog, when there is one, starts the run the check did not pass.
            openDialog.mock.calls[0]?.[0].primaryButton?.onClick?.({} as any)
            await expectLogic(logic).toFinishAllListeners()
            expect(mockTrain).toHaveBeenCalledTimes(1)
        }
    )
})
