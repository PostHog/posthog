import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(5000)

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        await getFirstTeam(hub.postgres)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('uses the email queue', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('email')
    })

    it('extends CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
    })

    describe('pacing', () => {
        const buildWorker = (overrides: Partial<Hub> = {}) => {
            const config = { ...hub, ...overrides } as Hub
            return new CdpCyclotronWorkerEmail(config, createCdpConsumerDeps(hub), createMockJobQueue())
        }

        // Fake timers are scoped to each test (not beforeEach) so DB setup/teardown
        // in the outer beforeEach/afterEach still runs against real time.
        afterEach(() => {
            jest.useRealTimers()
        })

        it('holds the tick open when processing finishes faster than CDP_CYCLOTRON_BATCH_DELAY_MS', async () => {
            const worker = buildWorker({ CDP_CYCLOTRON_BATCH_DELAY_MS: 100 })

            // Parent processInvocations is synchronous (resolves on a microtask, no
            // simulated work). The safety belt should fill the full 100ms interval.
            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            jest.useFakeTimers()
            const t0 = Date.now()
            const promise = worker.processInvocations([])
            await jest.advanceTimersByTimeAsync(100)
            await promise

            expect(Date.now() - t0).toBe(100)
        })

        it('does not add extra delay when processing already took longer than CDP_CYCLOTRON_BATCH_DELAY_MS', async () => {
            const worker = buildWorker({ CDP_CYCLOTRON_BATCH_DELAY_MS: 50 })

            // Parent takes 150ms (simulated). The interval is only 50ms, so the
            // safety belt should be a no-op — total elapsed must equal the parent's
            // own time, not 150 + 50.
            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockImplementation(
                () => new Promise((r) => setTimeout(() => r([]), 150))
            )

            jest.useFakeTimers()
            const t0 = Date.now()
            const promise = worker.processInvocations([])
            await jest.advanceTimersByTimeAsync(150)
            await promise

            expect(Date.now() - t0).toBe(150)
        })

        it('returns the parent result unchanged', async () => {
            const worker = buildWorker({ CDP_CYCLOTRON_BATCH_DELAY_MS: 0 })

            const expected = [{ finished: true } as any, { finished: false } as any]
            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue(
                expected
            )

            const results = await worker.processInvocations([])
            expect(results).toBe(expected)
        })
    })
})
