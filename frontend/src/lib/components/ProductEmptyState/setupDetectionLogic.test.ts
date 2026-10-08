import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { createSetupDetectionLogic } from './setupDetectionLogic'
import type { ProductSetupStatus } from './types'

describe('createSetupDetectionLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    function buildLogic(
        detect: jest.Mock<Promise<ProductSetupStatus | null>, []>,
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
    it.each([
        ['has-data', 'has-data'],
        ['needs-setup', 'needs-setup'],
        ['waiting-for-data', 'waiting-for-data'],
        ['unknown', 'unknown'],
        [null, 'unknown'],
    ] as const)('pushes an initial detection of %s into productSetupStatusLogic as %s', async (status, expected) => {
        const logic = buildLogic(jest.fn().mockResolvedValue(status))
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe(expected)
    })

    it('fails open to unknown when detection fails before any answer', async () => {
        const logic = buildLogic(jest.fn().mockRejectedValue(new Error('network down')))
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('unknown')
    })

    it('detects once the project loads when mounted before it is known', async () => {
        projectLogic.actions.loadCurrentProjectSuccess(null)
        const detect = jest.fn<Promise<ProductSetupStatus | null>, []>().mockResolvedValue('needs-setup')
        const logic = buildLogic(detect)
        logic.mount()
        projectLogic.actions.loadCurrentProjectSuccess(null)
        await expectLogic(logic).toFinishAllListeners()
        expect(detect).not.toHaveBeenCalled()

        projectLogic.actions.loadCurrentProjectSuccess(MOCK_DEFAULT_PROJECT)
        projectLogic.actions.loadCurrentProjectSuccess(MOCK_DEFAULT_PROJECT)
        await expectLogic(logic).toFinishAllListeners()
        expect(detect).toHaveBeenCalledTimes(1)
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('needs-setup')
    })

    it.each([
        ['rejects', 'needs-setup'],
        ['returns null', 'needs-setup'],
        ['returns unknown', 'unknown'],
    ] as const)('handles a poll that %s after an existing answer', async (failure, expected) => {
        const detect = jest.fn<Promise<ProductSetupStatus | null>, []>().mockResolvedValueOnce('needs-setup')
        if (failure === 'rejects') {
            detect.mockRejectedValueOnce(new Error('blip'))
        } else if (failure === 'returns null') {
            detect.mockResolvedValueOnce(null)
        } else {
            detect.mockResolvedValueOnce('unknown')
        }
        const logic = buildLogic(detect)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.detectStatus()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe(expected)
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

    it('stops polling once a request 404s on a deleted or inaccessible project', async () => {
        jest.useFakeTimers()
        const detect = jest
            .fn<Promise<ProductSetupStatus>, []>()
            .mockResolvedValueOnce('needs-setup')
            .mockRejectedValue(new ApiError('Project not found.', 404, undefined, { detail: 'Project not found.' }))
        const logic = buildLogic(detect, 1000)
        logic.mount()
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(1)

        // The first poll tick 404s, which disposes the poll...
        jest.advanceTimersByTime(1000)
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(2)

        // ...so no later tick fires another doomed request.
        jest.advanceTimersByTime(5000)
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(2)
    })

    it('keeps polling on a generic failure that may recover', async () => {
        jest.useFakeTimers()
        const detect = jest
            .fn<Promise<ProductSetupStatus>, []>()
            .mockResolvedValueOnce('needs-setup')
            .mockRejectedValue(new Error('transient blip'))
        const logic = buildLogic(detect, 1000)
        logic.mount()
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(1)

        jest.advanceTimersByTime(1000)
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(2)

        // A non-404 failure leaves the poll running.
        jest.advanceTimersByTime(1000)
        await flushMicrotasks()
        expect(detect).toHaveBeenCalledTimes(3)
    })

    // Data catalog rechecked on every list load, re-running a slow probe after the gate had
    // already opened; a needs-setup scene must still flip when its first entity lands.
    it.each([
        ['needs-setup', 2, 'waiting-for-data'],
        ['has-data', 1, 'has-data'],
    ] as const)(
        'on a recheck action while %s, runs detection %s time(s) in total',
        async (initial, calls, expected) => {
            const detect = jest
                .fn<Promise<ProductSetupStatus>, []>()
                .mockResolvedValueOnce(initial)
                .mockResolvedValue('waiting-for-data')
            const logic = createSetupDetectionLogic({
                productKey: ProductKey.LOGS,
                path: ['test', 'setupDetectionLogic'],
                detect,
                recheckActionTypes: () => [teamLogic.actionTypes.updateCurrentTeamSuccess],
            }).build()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe(initial)

            teamLogic.actions.updateCurrentTeamSuccess(MOCK_DEFAULT_TEAM, undefined)
            await expectLogic(logic).toFinishAllListeners()
            expect(detect).toHaveBeenCalledTimes(calls)
            expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe(expected)
        }
    )

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

    describe('with revalidateCachedHasData', () => {
        function buildCached(
            detect: jest.Mock<Promise<ProductSetupStatus | null>, []>,
            revalidateCachedHasData: boolean
        ): ReturnType<ReturnType<typeof createSetupDetectionLogic>['build']> {
            return createSetupDetectionLogic({
                productKey: ProductKey.LOGS,
                path: ['test', 'setupDetectionLogic'],
                detect,
                cacheHasData: true,
                revalidateCachedHasData,
            }).build()
        }

        async function seedCachedHasData(): Promise<void> {
            const seed = buildCached(jest.fn().mockResolvedValue('has-data'), true)
            seed.mount()
            await expectLogic(seed).toFinishAllListeners()
            seed.unmount()
        }

        async function nextMountDetects(): Promise<boolean> {
            const detect = jest.fn<Promise<ProductSetupStatus | null>, []>().mockResolvedValue('needs-setup')
            const next = buildCached(detect, false)
            next.mount()
            await expectLogic(next).toFinishAllListeners()
            next.unmount()
            return detect.mock.calls.length > 0
        }

        function mountWithPendingRevalidation(): {
            logic: ReturnType<typeof buildCached>
            answer: (status: ProductSetupStatus) => void
        } {
            let answer: (status: ProductSetupStatus) => void = () => {}
            const logic = buildCached(
                jest.fn<Promise<ProductSetupStatus | null>, []>(() => new Promise((resolve) => (answer = resolve))),
                true
            )
            logic.mount()
            return { logic, answer: (status) => answer(status) }
        }

        function switchTeam(id: number): void {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id })
        }

        it.each(['needs-setup', 'waiting-for-data'] as const)(
            'keeps the mounted scene on has-data and drops the cache when the check answers %s',
            async (noData) => {
                await seedCachedHasData()
                const { logic, answer } = mountWithPendingRevalidation()
                expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('has-data')

                answer(noData)
                await expectLogic(logic).toFinishAllListeners()
                expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('has-data')
                logic.unmount()
                expect(await nextMountDetects()).toBe(true)
            }
        )

        it('clears only the original team cache when the team changes mid-check', async () => {
            const otherTeamId = MOCK_DEFAULT_TEAM.id + 1
            switchTeam(otherTeamId)
            await seedCachedHasData()
            switchTeam(MOCK_DEFAULT_TEAM.id)
            await seedCachedHasData()

            const { logic, answer } = mountWithPendingRevalidation()
            switchTeam(otherTeamId)
            answer('needs-setup')
            await expectLogic(logic).toFinishAllListeners()
            logic.unmount()

            expect(await nextMountDetects()).toBe(false)
            switchTeam(MOCK_DEFAULT_TEAM.id)
            expect(await nextMountDetects()).toBe(true)
        })

        it.each([
            ['rejects', () => Promise.reject(new Error('network down'))],
            ['returns null', () => Promise.resolve(null)],
            ['returns unknown', () => Promise.resolve('unknown' as const)],
        ])('keeps has-data and the cache when the background check %s', async (_, answer) => {
            await seedCachedHasData()
            const logic = buildCached(jest.fn<Promise<ProductSetupStatus | null>, []>(answer), true)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('has-data')
            logic.unmount()
            expect(await nextMountDetects()).toBe(false)
        })

        it('runs the revalidation once, and only after the project is known', async () => {
            await seedCachedHasData()
            projectLogic.actions.loadCurrentProjectSuccess(null)

            const detect = jest.fn<Promise<ProductSetupStatus | null>, []>(async () =>
                projectLogic.findMounted()?.values.currentProjectId ? 'needs-setup' : null
            )
            const logic = buildCached(detect, true)
            logic.mount()
            projectLogic.actions.loadCurrentProjectSuccess(null)
            await expectLogic(logic).toFinishAllListeners()
            expect(detect).not.toHaveBeenCalled()
            expect(productSetupStatusLogic({ productKey: ProductKey.LOGS }).values.status).toBe('has-data')

            projectLogic.actions.loadCurrentProjectSuccess(MOCK_DEFAULT_PROJECT)
            projectLogic.actions.loadCurrentProjectSuccess(MOCK_DEFAULT_PROJECT)
            await expectLogic(logic).toFinishAllListeners()
            expect(detect).toHaveBeenCalledTimes(1)
            logic.unmount()
            expect(await nextMountDetects()).toBe(true)
        })
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
