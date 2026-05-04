import { parseJSON } from '~/utils/json-parse'

import { NotificationService } from './notification.service'

describe('NotificationService', () => {
    let service: NotificationService
    let mockRedisSet: jest.Mock
    let mockRedisUseClient: jest.Mock
    let mockFetch: jest.Mock

    const payload = {
        type: 'workflow_rate_limited',
        teamId: 1,
        functionId: 'flow-123',
        functionName: 'My Workflow',
        createdById: 42,
    }

    beforeEach(() => {
        mockRedisSet = jest.fn().mockResolvedValue('OK')
        mockRedisUseClient = jest.fn((_opts: any, fn: any) => Promise.resolve(fn({ set: mockRedisSet })))
        mockFetch = jest.fn().mockResolvedValue({ fetchError: null, fetchResponse: { status: 200 } })

        service = new NotificationService({ useClient: mockRedisUseClient } as any, { fetch: mockFetch } as any)
    })

    it('should debounce via Redis SET NX with 24h TTL', async () => {
        await service.notify('hog_flow', payload)

        expect(mockRedisSet).toHaveBeenCalledWith(
            '@posthog/notification/hog_flow/workflow_rate_limited/1/flow-123',
            '1',
            'EX',
            86400,
            'NX'
        )
    })

    it('should POST to the correct URL for hog_flow scope', async () => {
        await service.notify('hog_flow', payload)

        expect(mockFetch).toHaveBeenCalledWith({
            urlPath: '/api/projects/1/internal/hog_flows/notify',
            fetchParams: {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: expect.any(String),
            },
        })
    })

    it('should include all payload fields in the request body', async () => {
        await service.notify('hog_flow', { ...payload, priority: 'normal', target: 'team' })

        const body = parseJSON(mockFetch.mock.calls[0][0].fetchParams.body)
        expect(body).toEqual({
            type: 'workflow_rate_limited',
            hog_flow_id: 'flow-123',
            hog_flow_name: 'My Workflow',
            created_by_id: 42,
            priority: 'normal',
            target: 'team',
        })
    })

    it('should default priority to normal and target to owner', async () => {
        await service.notify('hog_flow', payload)

        const body = parseJSON(mockFetch.mock.calls[0][0].fetchParams.body)
        expect(body.priority).toBe('normal')
        expect(body.target).toBe('owner')
    })

    it('should not POST when debounce key already exists', async () => {
        mockRedisSet.mockResolvedValue(null)

        await service.notify('hog_flow', payload)

        expect(mockRedisSet).toHaveBeenCalled()
        expect(mockFetch).not.toHaveBeenCalled()
    })

    it('should not throw when fetch fails', async () => {
        mockFetch.mockRejectedValue(new Error('Network error'))

        await expect(service.notify('hog_flow', payload)).resolves.toBeUndefined()
    })

    it('should not throw when Redis fails', async () => {
        mockRedisUseClient.mockRejectedValue(new Error('Redis down'))

        await expect(service.notify('hog_flow', payload)).resolves.toBeUndefined()
    })
})
