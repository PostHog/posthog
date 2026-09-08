import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { createSetupDetectionLogic } from './setupDetectionLogic'
import type { ProductSetupStatus } from './types'

describe('createSetupDetectionLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    function buildLogic(
        detect: jest.Mock<Promise<ProductSetupStatus>, []>,
        pollIntervalMs?: number
    ): ReturnType<ReturnType<typeof createSetupDetectionLogic>['build']> {
        const logic = createSetupDetectionLogic({
            productKey: ProductKey.LOGS,
            path: ['test', 'setupDetectionLogic'],
            detect,
            pollIntervalMs,
        })
        return logic.build()
    }

    // The factory's whole job is feeding the scene gate: a status that never
    // arrives strands every adopting product on the scene-level spinner.
    it.each([['has-data'], ['needs-setup'], ['waiting-for-data'], ['unknown']] as const)(
        'pushes a detected %s into productSetupStatusLogic',
        async (status) => {
            const logic = buildLogic(jest.fn().mockResolvedValue(status))
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe(status)
        }
    )

    it('fails open to unknown when detection fails before any answer', async () => {
        const logic = buildLogic(jest.fn().mockRejectedValue(new Error('network down')))
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('unknown')
    })

    it('never downgrades an existing answer on a poll blip', async () => {
        const detect = jest
            .fn<Promise<ProductSetupStatus>, []>()
            .mockResolvedValueOnce('needs-setup')
            .mockRejectedValueOnce(new Error('blip'))
        const logic = buildLogic(detect)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.detectStatus()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('needs-setup')
    })

    // `toFinishAllListeners` waits on real timers, so under fake timers flush
    // the microtask queue by hand instead.
    async function flushMicrotasks(): Promise<void> {
        for (let i = 0; i < 10; i++) {
            await Promise.resolve()
        }
    }

    it('polls until data arrives, then stops for good', async () => {
        jest.useFakeTimers()
        const detect = jest
            .fn<Promise<ProductSetupStatus>, []>()
            .mockResolvedValueOnce('needs-setup')
            .mockResolvedValue('has-data')
        const logic = buildLogic(detect, 1000)
        logic.mount()
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(1)

        // First tick re-detects and lands on has-data...
        jest.advanceTimersByTime(1000)
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(2)
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('has-data')

        // ...after which the poll is disposed: more ticks run no more detections.
        jest.advanceTimersByTime(5000)
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(2)
    })

    it('re-detects when a recheck action fires', async () => {
        const detect = jest
            .fn<Promise<ProductSetupStatus>, []>()
            .mockResolvedValueOnce('needs-setup')
            .mockResolvedValue('waiting-for-data')
        const logic = createSetupDetectionLogic({
            productKey: ProductKey.LOGS,
            path: ['test', 'setupDetectionLogic'],
            detect,
            recheckActionTypes: () => [teamLogic.actionTypes.updateCurrentTeamSuccess],
        }).build()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('needs-setup')

        // A team-setting flip (e.g. enabling exception autocapture) must refresh
        // the status right away, not on the next poll tick.
        teamLogic.actions.updateCurrentTeamSuccess(MOCK_DEFAULT_TEAM, undefined)
        await expectLogic(logic).toFinishAllListeners()
        expect(detect).toHaveBeenCalledTimes(2)
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('waiting-for-data')
    })

    it('with cacheHasData, remembers has-data and skips detection on the next mount', async () => {
        const onDetected = jest.fn()
        const buildCached = (
            detect: jest.Mock<Promise<ProductSetupStatus>, []>
        ): ReturnType<ReturnType<typeof createSetupDetectionLogic>['build']> =>
            createSetupDetectionLogic({
                productKey: ProductKey.LOGS,
                path: ['test', 'setupDetectionLogic'],
                detect,
                cacheHasData: true,
                onDetected,
            }).build()

        const first = buildCached(jest.fn().mockResolvedValue('has-data'))
        first.mount()
        await expectLogic(first).toFinishAllListeners()
        first.unmount()
        onDetected.mockClear()

        // A stale-cached needs-setup would gate projects with real data, so only
        // has-data may skip detection.
        const detect = jest.fn<Promise<ProductSetupStatus>, []>().mockResolvedValue('needs-setup')
        const second = buildCached(detect)
        second.mount()
        await expectLogic(second).toFinishAllListeners()
        expect(detect).not.toHaveBeenCalled()
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('has-data')
        expect(onDetected).toHaveBeenCalledWith('has-data')
    })

    it('does not poll when no interval is configured', async () => {
        jest.useFakeTimers()
        const detect = jest.fn<Promise<ProductSetupStatus>, []>().mockResolvedValue('needs-setup')
        const logic = buildLogic(detect)
        logic.mount()
        await flushMicrotasks()
        jest.advanceTimersByTime(60000)
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(1)
    })
})
