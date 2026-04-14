import { KafkaProducerWrapper } from '../../kafka/producer'
import { SingleIngestionOutput } from './single-ingestion-output'
import { TeamRoutedIngestionOutput } from './team-routed-ingestion-output'

function createMockProducer(): jest.Mocked<KafkaProducerWrapper> {
    return {
        checkConnection: jest.fn().mockResolvedValue(undefined),
        checkTopicExists: jest.fn().mockResolvedValue(undefined),
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<KafkaProducerWrapper>
}

describe('TeamRoutedIngestionOutput', () => {
    let defaultProducer: jest.Mocked<KafkaProducerWrapper>
    let teamProducer: jest.Mocked<KafkaProducerWrapper>
    let defaultOutput: SingleIngestionOutput
    let teamOutput: SingleIngestionOutput
    let routed: TeamRoutedIngestionOutput

    beforeEach(() => {
        defaultProducer = createMockProducer()
        teamProducer = createMockProducer()
        defaultOutput = new SingleIngestionOutput('events', 'events_json', defaultProducer, 'DEFAULT')
        teamOutput = new SingleIngestionOutput('events', 'events_json', teamProducer, 'WARPSTREAM')
        routed = new TeamRoutedIngestionOutput(defaultOutput, teamOutput, new Set([2, 42]))
    })

    describe('produce', () => {
        it('routes to team output when teamId matches', async () => {
            await routed.produce({ key: Buffer.from('k'), value: Buffer.from('v'), teamId: 2 })

            expect(teamProducer.produce).toHaveBeenCalledTimes(1)
            expect(defaultProducer.produce).not.toHaveBeenCalled()
        })

        it('routes to default output when teamId does not match', async () => {
            await routed.produce({ key: Buffer.from('k'), value: Buffer.from('v'), teamId: 99 })

            expect(defaultProducer.produce).toHaveBeenCalledTimes(1)
            expect(teamProducer.produce).not.toHaveBeenCalled()
        })

        it('routes to default output when teamId is undefined', async () => {
            await routed.produce({ key: Buffer.from('k'), value: Buffer.from('v') })

            expect(defaultProducer.produce).toHaveBeenCalledTimes(1)
            expect(teamProducer.produce).not.toHaveBeenCalled()
        })
    })

    describe('queueMessages', () => {
        it('splits batch by team membership', async () => {
            await routed.queueMessages([
                { value: Buffer.from('default-1'), teamId: 1 },
                { value: Buffer.from('team-2'), teamId: 2 },
                { value: Buffer.from('default-3'), teamId: 3 },
                { value: Buffer.from('team-42'), teamId: 42 },
            ])

            expect(defaultProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(teamProducer.queueMessages).toHaveBeenCalledTimes(1)

            // Default producer gets messages for non-matching teams
            const defaultCall = defaultProducer.queueMessages.mock.calls[0][0] as { messages: unknown[] }
            expect(defaultCall.messages).toHaveLength(2)

            // Team producer gets messages for matching teams
            const teamCall = teamProducer.queueMessages.mock.calls[0][0] as { messages: unknown[] }
            expect(teamCall.messages).toHaveLength(2)
        })

        it('sends all to default when no teamId matches', async () => {
            await routed.queueMessages([{ value: Buffer.from('a'), teamId: 99 }, { value: Buffer.from('b') }])

            expect(defaultProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(teamProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('sends all to team output when all teamIds match', async () => {
            await routed.queueMessages([
                { value: Buffer.from('a'), teamId: 2 },
                { value: Buffer.from('b'), teamId: 42 },
            ])

            expect(teamProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(defaultProducer.queueMessages).not.toHaveBeenCalled()
        })

        it('handles empty batch', async () => {
            await routed.queueMessages([])

            expect(defaultProducer.queueMessages).not.toHaveBeenCalled()
            expect(teamProducer.queueMessages).not.toHaveBeenCalled()
        })
    })

    describe('checkHealth', () => {
        it('checks both outputs', async () => {
            await routed.checkHealth(5000)

            expect(defaultProducer.checkConnection).toHaveBeenCalledTimes(1)
            expect(teamProducer.checkConnection).toHaveBeenCalledTimes(1)
        })

        it('propagates failure from either output', async () => {
            teamProducer.checkConnection.mockRejectedValue(new Error('WS down'))

            await expect(routed.checkHealth(5000)).rejects.toThrow('WS down')
        })
    })

    describe('checkTopicExists', () => {
        it('checks both outputs', async () => {
            await routed.checkTopicExists(5000)

            expect(defaultProducer.checkTopicExists).toHaveBeenCalledTimes(1)
            expect(teamProducer.checkTopicExists).toHaveBeenCalledTimes(1)
        })
    })
})
