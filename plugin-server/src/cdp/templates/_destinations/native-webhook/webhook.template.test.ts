import { template } from './webhook.template'

describe('native webhook template', () => {
    it('should work with default mapping', async () => {
        const mockRequest = jest.fn().mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ message: 'Success' }),
            text: () => Promise.resolve(JSON.stringify({ message: 'Success' })),
            headers: {},
        })

        const payload = {
            url: 'https://example.com/webhook',
            method: 'POST',
            body: { event: '{event}', person: '{person}' },
            headers: { 'Content-Type': 'application/json' },
        }

        await template.perform(mockRequest, { payload })

        expect(mockRequest).toHaveBeenCalledTimes(1)
        expect(mockRequest).toHaveBeenCalledWith('https://example.com/webhook', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            json: { event: '{event}', person: '{person}' },
        })
    })
})
