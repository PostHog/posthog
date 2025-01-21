import { Message } from 'node-rdkafka'

import { KafkaMetrics } from '../../../../../src/main/ingestion-queues/session-recording-v2/kafka/metrics'
import { KafkaParser } from '../../../../../src/main/ingestion-queues/session-recording-v2/kafka/parser'
import { TeamFilter } from '../../../../../src/main/ingestion-queues/session-recording-v2/teams/team-filter'
import { TeamService } from '../../../../../src/main/ingestion-queues/session-recording-v2/teams/team-service'
import { Team } from '../../../../../src/main/ingestion-queues/session-recording-v2/teams/types'

jest.mock('../../../../../src/main/ingestion-queues/session-recording-v2/teams/team-service')
jest.mock('../../../../../src/main/ingestion-queues/session-recording-v2/kafka/parser')

const validTeam: Team = {
    teamId: 1,
    consoleLogIngestionEnabled: true,
}

const createSessionRecordingMessage = (token?: string, timestamp = Date.now()): Message => ({
    value: Buffer.from('test'),
    size: 4,
    topic: 'test',
    offset: 0,
    partition: 0,
    timestamp,
    headers: token ? [{ token }] : undefined,
})

const createParsedMessage = (offset = 0, timestamp = Date.now()) => ({
    distinct_id: 'distinct_id',
    session_id: 'session_id',
    metadata: {
        partition: 0,
        topic: 'test',
        offset,
        timestamp,
        rawSize: 100,
    },
    eventsByWindowId: {},
    eventsRange: { start: 0, end: 0 },
})

describe('TeamFilter', () => {
    let teamFilter: TeamFilter
    let teamService: jest.Mocked<TeamService>
    let kafkaMetrics: jest.Mocked<KafkaMetrics>
    let kafkaParser: jest.Mocked<KafkaParser>

    beforeEach(() => {
        jest.clearAllMocks()
        teamService = new TeamService() as jest.Mocked<TeamService>
        kafkaMetrics = new KafkaMetrics() as jest.Mocked<KafkaMetrics>
        kafkaParser = new KafkaParser(kafkaMetrics) as jest.Mocked<KafkaParser>
        teamFilter = new TeamFilter(teamService, kafkaParser)
    })

    describe('team token validation', () => {
        it('processes messages with valid team token', async () => {
            const message = createSessionRecordingMessage('valid-token')
            const parsedMessage = createParsedMessage()

            teamService.getTeamByToken.mockResolvedValueOnce(validTeam)
            kafkaParser.parseMessage.mockResolvedValueOnce(parsedMessage)

            const result = await teamFilter.parseBatch([message])

            expect(result).toEqual([{ team: validTeam, message: parsedMessage }])
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('valid-token')
            expect(teamService.getTeamByToken).toHaveBeenCalledTimes(1)
        })

        it('drops messages with no token in header', async () => {
            const message = createSessionRecordingMessage()
            const result = await teamFilter.parseBatch([message])

            expect(result).toEqual([])
            expect(teamService.getTeamByToken).not.toHaveBeenCalled()
            expect(kafkaParser.parseMessage).not.toHaveBeenCalled()
        })

        it('drops messages with invalid team tokens', async () => {
            const message = createSessionRecordingMessage('invalid-token')
            teamService.getTeamByToken.mockResolvedValueOnce(null)

            const result = await teamFilter.parseBatch([message])

            expect(result).toEqual([])
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('invalid-token')
            expect(teamService.getTeamByToken).toHaveBeenCalledTimes(1)
            expect(kafkaParser.parseMessage).not.toHaveBeenCalled()
        })
    })

    describe('message parsing', () => {
        beforeEach(() => {
            teamService.getTeamByToken.mockResolvedValue(validTeam)
        })

        it('processes valid parsed messages', async () => {
            const message = createSessionRecordingMessage('token')
            const parsedMessage = createParsedMessage()
            kafkaParser.parseMessage.mockResolvedValueOnce(parsedMessage)

            const result = await teamFilter.parseBatch([message])

            expect(result).toEqual([{ team: validTeam, message: parsedMessage }])
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token')
            expect(teamService.getTeamByToken).toHaveBeenCalledTimes(1)
        })

        it('drops messages that fail parsing', async () => {
            const message = createSessionRecordingMessage('token')
            kafkaParser.parseMessage.mockResolvedValueOnce(null)

            const result = await teamFilter.parseBatch([message])

            expect(result).toEqual([])
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token')
            expect(teamService.getTeamByToken).toHaveBeenCalledTimes(1)
        })
    })

    describe('batch processing', () => {
        beforeEach(() => {
            teamService.getTeamByToken.mockResolvedValue(validTeam)
        })

        it('processes multiple messages in order', async () => {
            const timestamp = Date.now()
            const messages = [
                createSessionRecordingMessage('token1', timestamp),
                createSessionRecordingMessage('token2', timestamp + 1),
            ]

            const parsedMessages = [createParsedMessage(0, timestamp), createParsedMessage(1, timestamp + 1)]

            kafkaParser.parseMessage.mockResolvedValueOnce(parsedMessages[0]).mockResolvedValueOnce(parsedMessages[1])

            const result = await teamFilter.parseBatch(messages)

            expect(result).toEqual([
                { team: validTeam, message: parsedMessages[0] },
                { team: validTeam, message: parsedMessages[1] },
            ])
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token1')
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token2')
            expect(teamService.getTeamByToken).toHaveBeenCalledTimes(2)
        })

        it('processes messages with different teams', async () => {
            const timestamp = Date.now()
            const messages = [
                createSessionRecordingMessage('token1', timestamp),
                createSessionRecordingMessage('token2', timestamp + 1),
            ]

            const parsedMessages = [createParsedMessage(0, timestamp), createParsedMessage(1, timestamp + 1)]

            const team2 = { ...validTeam, teamId: 2 }

            teamService.getTeamByToken.mockResolvedValueOnce(validTeam).mockResolvedValueOnce(team2)

            kafkaParser.parseMessage.mockResolvedValueOnce(parsedMessages[0]).mockResolvedValueOnce(parsedMessages[1])

            const result = await teamFilter.parseBatch(messages)

            expect(result).toEqual([
                { team: validTeam, message: parsedMessages[0] },
                { team: team2, message: parsedMessages[1] },
            ])
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token1')
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token2')
            expect(teamService.getTeamByToken).toHaveBeenCalledTimes(2)
        })

        it('handles mixed valid and invalid messages in batch', async () => {
            const messages = [
                createSessionRecordingMessage('token1'),
                createSessionRecordingMessage(), // No token
                createSessionRecordingMessage('token2'),
            ]

            kafkaParser.parseMessage
                .mockResolvedValueOnce(createParsedMessage(0))
                .mockResolvedValueOnce(createParsedMessage(2))

            const result = await teamFilter.parseBatch(messages)

            expect(result).toHaveLength(2)
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token1')
            expect(teamService.getTeamByToken).toHaveBeenCalledWith('token2')
            expect(teamService.getTeamByToken).toHaveBeenCalledTimes(2)
        })
    })
})
