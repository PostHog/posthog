import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { Hub } from '../../types'
import { CdpCyclotronWorkerEmailTransactional } from './cdp-cyclotron-worker-email-transactional.consumer'

jest.setTimeout(5000)

describe('CdpCyclotronWorkerEmailTransactional', () => {
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

    it('should set queue to emailtransactional', () => {
        const worker = new CdpCyclotronWorkerEmailTransactional(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('emailtransactional')
    })

    it('should extend CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmailTransactional(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmailTransactional')
    })
})
