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
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    it('should set queue to email', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('email')
    })

    it('should extend CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
    })

    describe('rate limiter integration', () => {
        // When SES_RATE_LIMITER_VALKEY_HOST is unset (local-dev fallback), no
        // limiter is constructed and the worker dequeues unthrottled. The
        // queue's setDynamicBatchLimit is never called, so any queue backend
        // is allowed (we don't enforce postgres-v2 when rate limiting is off).
        it('does not construct a RateLimiterService when no Valkey host is set', () => {
            const worker = new CdpCyclotronWorkerEmail(
                { ...hub, SES_RATE_LIMITER_VALKEY_HOST: '' },
                createCdpConsumerDeps(hub),
                createMockJobQueue()
            )

            expect(worker['sesRateLimiter']).toBeNull()
        })
    })
})
