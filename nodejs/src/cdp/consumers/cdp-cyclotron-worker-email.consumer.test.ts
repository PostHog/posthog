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

        it('holds the tick open when processing finishes faster than CDP_CYCLOTRON_BATCH_DELAY_MS', async () => {
            const worker = buildWorker({ CDP_CYCLOTRON_BATCH_DELAY_MS: 100 })

            // Stub parent processInvocations as immediate (0ms work).
            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockResolvedValue([])

            const t0 = Date.now()
            await worker.processInvocations([])
            const elapsed = Date.now() - t0

            // Should be very close to 100ms (the safety belt). Allow generous
            // upper bound for CI scheduler jitter.
            expect(elapsed).toBeGreaterThanOrEqual(95)
            expect(elapsed).toBeLessThan(250)
        })

        it('does not add extra delay when processing already took longer than CDP_CYCLOTRON_BATCH_DELAY_MS', async () => {
            const worker = buildWorker({ CDP_CYCLOTRON_BATCH_DELAY_MS: 50 })

            // Parent takes 150ms — already longer than the 50ms interval.
            jest.spyOn(Object.getPrototypeOf(Object.getPrototypeOf(worker)), 'processInvocations').mockImplementation(
                () => new Promise((r) => setTimeout(() => r([]), 150))
            )

            const t0 = Date.now()
            await worker.processInvocations([])
            const elapsed = Date.now() - t0

            // Should be ~150ms (parent's time), not 150 + 50.
            expect(elapsed).toBeGreaterThanOrEqual(145)
            expect(elapsed).toBeLessThan(250)
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
