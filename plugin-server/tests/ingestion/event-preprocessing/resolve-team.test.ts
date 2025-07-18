import { resolveTeam } from '../../../src/ingestion/event-preprocessing/resolve-team'
import { Hub, IncomingEvent } from '../../../src/types'
import { populateTeamDataStep } from '../../../src/worker/ingestion/event-pipeline/populateTeamDataStep'

// Mock the populateTeamDataStep function
jest.mock('../../../src/worker/ingestion/event-pipeline/populateTeamDataStep')
const mockPopulateTeamDataStep = populateTeamDataStep as jest.MockedFunction<typeof populateTeamDataStep>

describe('resolveTeam', () => {
    let mockHub: Pick<Hub, 'teamManager'>
    let mockIncomingEvent: IncomingEvent

    beforeEach(() => {
        mockHub = {
            teamManager: {} as any,
        }

        mockIncomingEvent = {
            event: {
                token: 'test-token-123',
                distinct_id: 'test-user-456',
                event: 'test-event',
                properties: { testProp: 'testValue' },
                ip: '127.0.0.1',
                site_url: 'https://example.com',
                now: new Date().toISOString(),
                uuid: '123e4567-e89b-12d3-a456-426614174000',
            },
            message: {} as any,
        }

        jest.clearAllMocks()
    })

    it('should return IncomingEventWithTeam when populateTeamDataStep succeeds', async () => {
        const mockResult = {
            event: {
                token: 'test-token-123',
                distinct_id: 'test-user-456',
                event: 'test-event',
                properties: { testProp: 'testValue' },
                ip: '127.0.0.1',
                site_url: 'https://example.com',
                now: new Date().toISOString(),
                uuid: '123e4567-e89b-12d3-a456-426614174000',
            },
            team: {
                id: 1,
                name: 'Test Team',
                person_processing_opt_out: false,
            } as any,
        }

        mockPopulateTeamDataStep.mockResolvedValue(mockResult)

        const result = await resolveTeam(mockHub, mockIncomingEvent)

        expect(result).toEqual({
            event: mockResult.event,
            team: mockResult.team,
            message: mockIncomingEvent.message,
        })
        expect(mockPopulateTeamDataStep).toHaveBeenCalledWith(mockHub, mockIncomingEvent.event)
    })

    it('should return null when populateTeamDataStep returns null', async () => {
        mockPopulateTeamDataStep.mockResolvedValue(null)

        const result = await resolveTeam(mockHub, mockIncomingEvent)

        expect(result).toBeNull()
        expect(mockPopulateTeamDataStep).toHaveBeenCalledWith(mockHub, mockIncomingEvent.event)
    })

    it('should handle different event data', async () => {
        const differentEvent = {
            event: {
                token: 'different-token-789',
                distinct_id: 'different-user-012',
                event: 'different-event',
                properties: { differentProp: 'differentValue' },
                ip: '192.168.1.1',
                site_url: 'https://different.com',
                now: new Date().toISOString(),
                uuid: '987fcdeb-51a2-43d1-b789-987654321000',
            },
            message: {} as any,
        }

        const mockResult = {
            event: differentEvent.event,
            team: {
                id: 2,
                name: 'Different Team',
                person_processing_opt_out: true,
            } as any,
        }

        mockPopulateTeamDataStep.mockResolvedValue(mockResult)

        const result = await resolveTeam(mockHub, differentEvent)

        expect(result).toEqual({
            event: mockResult.event,
            team: mockResult.team,
            message: differentEvent.message,
        })
        expect(mockPopulateTeamDataStep).toHaveBeenCalledWith(mockHub, differentEvent.event)
    })

    it('should propagate errors from populateTeamDataStep', async () => {
        const error = new Error('Database connection failed')
        mockPopulateTeamDataStep.mockRejectedValue(error)

        await expect(resolveTeam(mockHub, mockIncomingEvent)).rejects.toThrow('Database connection failed')
        expect(mockPopulateTeamDataStep).toHaveBeenCalledWith(mockHub, mockIncomingEvent.event)
    })
})
