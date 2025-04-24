import { Hub } from '~/src/types'
import { closeHub, createHub } from '~/src/utils/db/hub'

import { HogFunctionManagerService } from './hog-function-manager.service'
import { CyclotronJobQueue } from './job-queue'

describe('CyclotronJobQueue', () => {
    let hub: Hub
    let hogFunctionManager: HogFunctionManagerService
    let mockConsumeBatch: jest.Mock

    beforeEach(async () => {
        hub = await createHub()
        hogFunctionManager = new HogFunctionManagerService(hub)
        mockConsumeBatch = jest.fn()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('cyclotron', () => {
        beforeEach(() => {
            hub.CDP_CYCLOTRON_DELIVERY_MODE = 'cyclotron'
        })

        it('should initialise', () => {
            const queue = new CyclotronJobQueue(hub, 'hog', hogFunctionManager, mockConsumeBatch)
            expect(queue).toBeDefined()
            expect(queue['implementation']).toBe('cyclotron')
        })
    })

    describe('kafka', () => {
        beforeEach(() => {
            hub.CDP_CYCLOTRON_DELIVERY_MODE = 'kafka'
        })

        it('should initialise', () => {
            const queue = new CyclotronJobQueue(hub, 'hog', hogFunctionManager, mockConsumeBatch)
            expect(queue).toBeDefined()
            expect(queue['implementation']).toBe('kafka')
        })
    })
})
