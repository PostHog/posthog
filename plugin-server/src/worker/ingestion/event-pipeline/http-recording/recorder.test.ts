import { DestinationHttpRecorder } from './recorder'
import { HttpInteraction } from './types'

describe('DestinationHttpRecorder', () => {
    let recorder: DestinationHttpRecorder

    beforeEach(() => {
        recorder = new DestinationHttpRecorder()
    })

    describe('recording lifecycle', () => {
        it('should start a new recording', () => {
            recorder.startRecording('event-123', 1, 'destination-1')
            const recording = recorder.stopRecording()

            expect(recording.metadata).toEqual(
                expect.objectContaining({
                    eventUuid: 'event-123',
                    teamId: 1,
                    destinationId: 'destination-1',
                })
            )
            expect(recording.interactions).toEqual([])
        })

        it('should throw when starting a recording while one is in progress', () => {
            recorder.startRecording('event-123', 1, 'destination-1')
            expect(() => recorder.startRecording('event-456', 1, 'destination-1')).toThrow(
                'Recording already in progress'
            )
        })

        it('should throw when stopping a recording when none is in progress', () => {
            expect(() => recorder.stopRecording()).toThrow('No recording in progress')
        })

        it('should throw when recording interaction when no recording is in progress', () => {
            const interaction = createMockInteraction()
            expect(() => recorder.recordInteraction(interaction)).toThrow('No recording in progress')
        })
    })

    describe('recording interactions', () => {
        it('should record interactions in sequence', () => {
            recorder.startRecording('event-123', 1, 'destination-1')

            const interaction1 = createMockInteraction({ id: '1' })
            const interaction2 = createMockInteraction({ id: '2' })

            recorder.recordInteraction(interaction1)
            recorder.recordInteraction(interaction2)

            const recording = recorder.stopRecording()
            expect(recording.interactions).toEqual([interaction1, interaction2])
        })
    })

    describe('comparing recordings', () => {
        it('should identify identical recordings', () => {
            const interaction = createMockInteraction()
            const recording1 = createMockRecording([interaction])
            const recording2 = createMockRecording([interaction])

            const comparison = recorder.compareRecordings(recording1, recording2)
            expect(comparison.matches).toBe(true)
            expect(comparison.differences).toBeUndefined()
        })

        it('should identify missing interactions', () => {
            const interaction1 = createMockInteraction({ id: '1' })
            const interaction2 = createMockInteraction({ id: '2' })

            const recording1 = createMockRecording([interaction1, interaction2])
            const recording2 = createMockRecording([interaction1])

            const comparison = recorder.compareRecordings(recording1, recording2)
            expect(comparison.matches).toBe(false)
            expect(comparison.differences?.missing).toEqual([interaction2])
        })

        it('should identify additional interactions', () => {
            const interaction1 = createMockInteraction({ id: '1' })
            const interaction2 = createMockInteraction({ id: '2' })

            const recording1 = createMockRecording([interaction1])
            const recording2 = createMockRecording([interaction1, interaction2])

            const comparison = recorder.compareRecordings(recording1, recording2)
            expect(comparison.matches).toBe(false)
            expect(comparison.differences?.additional).toEqual([interaction2])
        })

        it('should identify differences in interactions', () => {
            const interaction1 = createMockInteraction({
                id: '1',
                request: {
                    method: 'GET',
                    url: 'https://api.example.com',
                    headers: {},
                },
            })

            const interaction2 = createMockInteraction({
                id: '1',
                request: {
                    method: 'POST',
                    url: 'https://api.example.com',
                    headers: {},
                },
            })

            const recording1 = createMockRecording([interaction1])
            const recording2 = createMockRecording([interaction2])

            const comparison = recorder.compareRecordings(recording1, recording2)
            expect(comparison.matches).toBe(false)
            expect(comparison.differences?.different[0].differences).toContain('Method mismatch: GET != POST')
        })

        it('should handle case-insensitive header comparison', () => {
            const interaction1 = createMockInteraction({
                id: '1',
                request: {
                    method: 'GET',
                    url: 'https://api.example.com',
                    headers: { 'Content-Type': 'application/json' },
                },
            })

            const interaction2 = createMockInteraction({
                id: '1',
                request: {
                    method: 'GET',
                    url: 'https://api.example.com',
                    headers: { 'content-type': 'application/json' },
                },
            })

            const recording1 = createMockRecording([interaction1])
            const recording2 = createMockRecording([interaction2])

            const comparison = recorder.compareRecordings(recording1, recording2)
            expect(comparison.matches).toBe(true)
            expect(comparison.differences).toBeUndefined()
        })
    })
})

// Helper functions to create test data
function createMockInteraction(overrides: Partial<HttpInteraction> = {}): HttpInteraction {
    const defaultInteraction: HttpInteraction = {
        id: 'test-id',
        timestamp: Date.now(),
        request: {
            method: 'GET',
            url: 'https://api.example.com',
            headers: {},
            ...(overrides.request || {}),
        },
        response: {
            status: 200,
            headers: {},
            body: { success: true },
            ...(overrides.response || {}),
        },
    }

    return {
        ...defaultInteraction,
        ...overrides,
        request: {
            ...defaultInteraction.request,
            ...(overrides.request || {}),
        },
        response: {
            ...defaultInteraction.response,
            ...(overrides.response || {}),
        },
    }
}

function createMockRecording(interactions: HttpInteraction[]) {
    return {
        metadata: {
            eventUuid: 'test-event',
            teamId: 1,
            destinationId: 'test-destination',
            timestamp: Date.now(),
        },
        interactions,
    }
}
