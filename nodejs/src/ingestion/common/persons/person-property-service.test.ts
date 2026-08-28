import { PersonPropertyService } from './person-property-service'
import { PersonhogFenceTimeoutError } from './personhog-persons-store'

describe('PersonPropertyService', () => {
    it('a fence wait that ran out its ceiling fails the batch instead of stacking retries', async () => {
        // One ceiling already covers a whole merge with its transport
        // retries; three stacked exceed the consumer's poll interval and
        // convert the intended redelivery into an eviction.
        const fetchForUpdate = jest.fn().mockRejectedValue(new PersonhogFenceTimeoutError('1:7', 120_000))
        const context = {
            team: { id: 1 },
            distinctId: 'd1',
            personStore: { fetchForUpdate },
            outputs: [],
        } as any
        const service = new PersonPropertyService(context)

        await expect(service.handleUpdate()).rejects.toBeInstanceOf(PersonhogFenceTimeoutError)
        expect(fetchForUpdate).toHaveBeenCalledTimes(1)
    })
})
