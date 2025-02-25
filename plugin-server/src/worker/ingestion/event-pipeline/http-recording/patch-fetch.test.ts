import { patchTrackedFetch, restoreTrackedFetch } from './patch-fetch'
import { DestinationHttpRecorder } from './recorder'

describe('patchTrackedFetch', () => {
    let mockFetchModule: any
    let mockRecorder: DestinationHttpRecorder
    let originalFetch: jest.Mock
    let mockResponse: any

    beforeEach(() => {
        // Mock response
        mockResponse = {
            status: 200,
            headers: new Map([['content-type', 'application/json']]),
            clone: jest.fn().mockReturnThis(),
            json: jest.fn().mockResolvedValue({ success: true }),
            text: jest.fn().mockResolvedValue('{"success":true}'),
        }

        // Mock fetch function
        originalFetch = jest.fn().mockResolvedValue(mockResponse)

        // Mock fetch module
        mockFetchModule = {
            trackedFetch: originalFetch,
        }

        // Mock recorder
        mockRecorder = {
            startRecording: jest.fn(),
            recordInteraction: jest.fn(),
            stopRecording: jest.fn(),
            compareRecordings: jest.fn(),
        } as unknown as DestinationHttpRecorder
    })

    it('should patch the trackedFetch function', () => {
        patchTrackedFetch(mockFetchModule, mockRecorder)

        expect(mockFetchModule.trackedFetch).not.toBe(originalFetch)
    })

    it('should restore the original trackedFetch function', () => {
        patchTrackedFetch(mockFetchModule, mockRecorder)
        restoreTrackedFetch(mockFetchModule)

        expect(mockFetchModule.trackedFetch).toBe(originalFetch)
    })

    it('should record successful HTTP interactions', async () => {
        patchTrackedFetch(mockFetchModule, mockRecorder)

        await mockFetchModule.trackedFetch('https://api.example.com', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: 'test' }),
        })

        expect(mockRecorder.recordInteraction).toHaveBeenCalledTimes(1)

        const recordedInteraction = (mockRecorder.recordInteraction as jest.Mock).mock.calls[0][0]
        expect(recordedInteraction.request.method).toBe('POST')
        expect(recordedInteraction.request.url).toBe('https://api.example.com')
        expect(recordedInteraction.response.status).toBe(200)
    })

    it('should record failed HTTP interactions', async () => {
        patchTrackedFetch(mockFetchModule, mockRecorder)

        const error = new Error('Network error')
        originalFetch.mockRejectedValueOnce(error)

        await expect(mockFetchModule.trackedFetch('https://api.example.com')).rejects.toThrow('Network error')

        expect(mockRecorder.recordInteraction).toHaveBeenCalledTimes(1)

        const recordedInteraction = (mockRecorder.recordInteraction as jest.Mock).mock.calls[0][0]
        expect(recordedInteraction.request.method).toBe('GET')
        expect(recordedInteraction.request.url).toBe('https://api.example.com')
        expect(recordedInteraction.response.status).toBe(0)
        expect(recordedInteraction.response.body.error).toBe('Network error')
    })
})
