import { PersonEventProcessor } from './person-event-processor'
import { PersonhogFenceTimeoutError } from './personhog-persons-store'

describe('PersonEventProcessor', () => {
    it('a fence wait that ran out its ceiling on the shortcut is not waited out twice', async () => {
        // The fallback path would open a second full ceiling on the same
        // still-held fence, putting one event past the consumer's poll
        // interval; the batch fails instead and redelivery meets the fence
        // resolved.
        const mergeService = {
            handleIdentifyOrAlias: jest.fn().mockResolvedValue({
                success: true,
                person: { id: '7', team_id: 1 },
                kafkaAck: Promise.resolve(),
                needsPersonUpdate: true,
            }),
        } as any
        const propertyService = {
            updatePersonProperties: jest.fn().mockRejectedValue(new PersonhogFenceTimeoutError('1:7', 120_000)),
            handleUpdate: jest.fn(),
        } as any
        const processor = new PersonEventProcessor({} as any, propertyService, mergeService)

        await expect(processor.processEvent()).rejects.toBeInstanceOf(PersonhogFenceTimeoutError)
        expect(propertyService.handleUpdate).not.toHaveBeenCalled()
    })
})
