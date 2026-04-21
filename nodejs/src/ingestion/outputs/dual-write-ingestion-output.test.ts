import { KafkaProducerWrapper } from '../../kafka/producer'
import { DualWriteIngestionOutput, keyHashBucket, shouldRouteToSecondary } from './dual-write-ingestion-output'
import { SingleIngestionOutput } from './single-ingestion-output'

describe('DualWriteIngestionOutput', () => {
    function createMockProducer(): KafkaProducerWrapper {
        return {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
            checkConnection: jest.fn().mockResolvedValue(undefined),
            checkTopicExists: jest.fn().mockResolvedValue(undefined),
        } as unknown as KafkaProducerWrapper
    }

    function createOutputs(mode: 'copy' | 'move', percentage: number) {
        const primaryProducer = createMockProducer()
        const secondaryProducer = createMockProducer()
        const primary = new SingleIngestionOutput('test', 'primary_topic', primaryProducer, 'PRIMARY')
        const secondary = new SingleIngestionOutput('test', 'secondary_topic', secondaryProducer, 'SECONDARY')
        const output = new DualWriteIngestionOutput(primary, secondary, mode, percentage)
        return { output, primaryProducer, secondaryProducer }
    }

    describe('copy mode', () => {
        it('produce sends to both primary and secondary when key hashes below percentage', async () => {
            // key-a hashes to 26, so at percentage=50 it routes to secondary
            const { output, primaryProducer, secondaryProducer } = createOutputs('copy', 50)

            await output.produce({ key: Buffer.from('key-a'), value: Buffer.from('v') })

            expect(primaryProducer.produce).toHaveBeenCalledTimes(1)
            expect(secondaryProducer.produce).toHaveBeenCalledTimes(1)
        })

        it('produce sends to primary only when key hashes above percentage', async () => {
            // key-c hashes to 88, so at percentage=50 it does NOT route to secondary
            const { output, primaryProducer, secondaryProducer } = createOutputs('copy', 50)

            await output.produce({ key: Buffer.from('key-c'), value: Buffer.from('v') })

            expect(primaryProducer.produce).toHaveBeenCalledTimes(1)
            expect(secondaryProducer.produce).not.toHaveBeenCalled()
        })

        it('produce always sends to primary regardless of percentage', async () => {
            const { output, primaryProducer } = createOutputs('copy', 0)

            await output.produce({ key: Buffer.from('key-a'), value: Buffer.from('v') })

            expect(primaryProducer.produce).toHaveBeenCalledTimes(1)
        })

        it('queueMessages sends all to primary and matching subset to secondary', async () => {
            // key-a hashes to 26 (below 50), key-c hashes to 88 (above 50)
            const { output, primaryProducer, secondaryProducer } = createOutputs('copy', 50)
            const msgA = { key: Buffer.from('key-a'), value: Buffer.from('1') }
            const msgC = { key: Buffer.from('key-c'), value: Buffer.from('2') }

            await output.queueMessages([msgA, msgC])

            expect(primaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'primary_topic',
                messages: [msgA, msgC],
            })
            expect(secondaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'secondary_topic',
                messages: [msgA],
            })
        })

        it('queueMessages skips secondary call when no messages match percentage', async () => {
            const { output, primaryProducer, secondaryProducer } = createOutputs('copy', 0)

            await output.queueMessages([{ key: Buffer.from('key-a'), value: Buffer.from('1') }])

            expect(primaryProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(secondaryProducer.queueMessages).not.toHaveBeenCalled()
        })
    })

    describe('move mode', () => {
        it('produce sends to secondary when key hashes below percentage', async () => {
            // key-a hashes to 26, below 50
            const { output, primaryProducer, secondaryProducer } = createOutputs('move', 50)

            await output.produce({ key: Buffer.from('key-a'), value: Buffer.from('v') })

            expect(primaryProducer.produce).not.toHaveBeenCalled()
            expect(secondaryProducer.produce).toHaveBeenCalledTimes(1)
        })

        it('produce sends to primary when key hashes above percentage', async () => {
            // key-c hashes to 88, above 50
            const { output, primaryProducer, secondaryProducer } = createOutputs('move', 50)

            await output.produce({ key: Buffer.from('key-c'), value: Buffer.from('v') })

            expect(primaryProducer.produce).toHaveBeenCalledTimes(1)
            expect(secondaryProducer.produce).not.toHaveBeenCalled()
        })

        it('queueMessages splits messages between primary and secondary by key hash', async () => {
            // At 50%: key-a(26)→secondary, key-b(7)→secondary, key-c(88)→primary, user-2(57)→primary
            const { output, primaryProducer, secondaryProducer } = createOutputs('move', 50)
            const msgA = { key: Buffer.from('key-a'), value: Buffer.from('a') }
            const msgB = { key: Buffer.from('key-b'), value: Buffer.from('b') }
            const msgC = { key: Buffer.from('key-c'), value: Buffer.from('c') }
            const msgU2 = { key: Buffer.from('user-2'), value: Buffer.from('u2') }

            await output.queueMessages([msgA, msgB, msgC, msgU2])

            expect(primaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'primary_topic',
                messages: [msgC, msgU2],
            })
            expect(secondaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'secondary_topic',
                messages: [msgA, msgB],
            })
        })

        it('queueMessages routes keyless messages to secondary when random < percentage', async () => {
            jest.spyOn(Math, 'random').mockReturnValue(0.3) // 30 < 50 → secondary
            const { output, primaryProducer, secondaryProducer } = createOutputs('move', 50)
            const msg = { value: Buffer.from('no-key') }

            await output.queueMessages([msg])

            expect(primaryProducer.queueMessages).not.toHaveBeenCalled()
            expect(secondaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'secondary_topic',
                messages: [msg],
            })
            jest.restoreAllMocks()
        })

        it('queueMessages routes keyless messages to primary when random >= percentage', async () => {
            jest.spyOn(Math, 'random').mockReturnValue(0.7) // 70 >= 50 → primary
            const { output, primaryProducer, secondaryProducer } = createOutputs('move', 50)
            const msg = { value: Buffer.from('no-key') }

            await output.queueMessages([msg])

            expect(primaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'primary_topic',
                messages: [msg],
            })
            expect(secondaryProducer.queueMessages).not.toHaveBeenCalled()
            jest.restoreAllMocks()
        })

        it('queueMessages splits mixed keyed and keyless messages', async () => {
            // keyless1: random=0.3 → 30 < 50 → secondary
            // keyless2: random=0.8 → 80 >= 50 → primary
            jest.spyOn(Math, 'random').mockReturnValueOnce(0.3).mockReturnValueOnce(0.8)
            const { output, primaryProducer, secondaryProducer } = createOutputs('move', 50)
            const keyless1 = { value: Buffer.from('no-key-1') }
            const msgC = { key: Buffer.from('key-c'), value: Buffer.from('c') } // hash 88 → primary
            const keyless2 = { value: Buffer.from('no-key-2') }
            const msgA = { key: Buffer.from('key-a'), value: Buffer.from('a') } // hash 26 → secondary

            await output.queueMessages([keyless1, msgC, keyless2, msgA])

            expect(primaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'primary_topic',
                messages: [msgC, keyless2],
            })
            expect(secondaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'secondary_topic',
                messages: [keyless1, msgA],
            })
            jest.restoreAllMocks()
        })

        it('queueMessages skips empty batches', async () => {
            // All keys hash below 50 → everything goes to secondary, primary not called
            const { output, primaryProducer, secondaryProducer } = createOutputs('move', 50)
            const msgA = { key: Buffer.from('key-a'), value: Buffer.from('a') } // hash 26
            const msgB = { key: Buffer.from('key-b'), value: Buffer.from('b') } // hash 7

            await output.queueMessages([msgA, msgB])

            expect(primaryProducer.queueMessages).not.toHaveBeenCalled()
            expect(secondaryProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'secondary_topic',
                messages: [msgA, msgB],
            })
        })
    })

    describe('health checks', () => {
        it('checks both primary and secondary producers', async () => {
            const { output, primaryProducer, secondaryProducer } = createOutputs('copy', 100)

            await output.checkHealth(5000)

            expect(primaryProducer.checkConnection).toHaveBeenCalledWith(5000)
            expect(secondaryProducer.checkConnection).toHaveBeenCalledWith(5000)
        })

        it('checks both topics exist', async () => {
            const { output, primaryProducer, secondaryProducer } = createOutputs('copy', 100)

            await output.checkTopicExists(5000)

            expect(primaryProducer.checkTopicExists).toHaveBeenCalledWith('primary_topic', 5000)
            expect(secondaryProducer.checkTopicExists).toHaveBeenCalledWith('secondary_topic', 5000)
        })
    })
})

describe('shouldRouteToSecondary', () => {
    it('returns false for null key at 0%', () => {
        expect(shouldRouteToSecondary(null, 0)).toBe(false)
    })

    it('returns true for null key at 100%', () => {
        expect(shouldRouteToSecondary(null, 100)).toBe(true)
    })

    it('returns false for undefined key at 0%', () => {
        expect(shouldRouteToSecondary(undefined, 0)).toBe(false)
    })

    it('returns true for undefined key at 100%', () => {
        expect(shouldRouteToSecondary(undefined, 100)).toBe(true)
    })

    it('routes null key to secondary when random < percentage', () => {
        jest.spyOn(Math, 'random').mockReturnValue(0.29) // 29 < 50 → true
        expect(shouldRouteToSecondary(null, 50)).toBe(true)
        jest.restoreAllMocks()
    })

    it('routes null key to primary when random >= percentage', () => {
        jest.spyOn(Math, 'random').mockReturnValue(0.5) // 50 >= 50 → false
        expect(shouldRouteToSecondary(null, 50)).toBe(false)
        jest.restoreAllMocks()
    })

    it('returns false when percentage is 0', () => {
        expect(shouldRouteToSecondary(Buffer.from('key-a'), 0)).toBe(false)
    })

    it('returns true when percentage is 100 and key is present', () => {
        expect(shouldRouteToSecondary(Buffer.from('key-a'), 100)).toBe(true)
    })

    it('is deterministic — same key always produces the same result', () => {
        const key = Buffer.from('test-key')
        const results = Array.from({ length: 10 }, () => shouldRouteToSecondary(key, 50))
        expect(new Set(results).size).toBe(1)
    })

    it('works with string keys', () => {
        // key-a as string should behave the same as key-a as Buffer
        expect(shouldRouteToSecondary('key-a', 50)).toBe(shouldRouteToSecondary(Buffer.from('key-a'), 50))
    })

    // FNV-1a hash values for known keys (verified empirically):
    //   key-a → 26, key-b → 7, key-c → 88, key-d → 21, key-e → 2
    //   user-1 → 0, user-2 → 57, user-3 → 38, user-4 → 43, user-5 → 24
    it.each([
        { key: 'key-a', pct: 50, expected: true, hash: 26 },
        { key: 'key-b', pct: 50, expected: true, hash: 7 },
        { key: 'key-c', pct: 50, expected: false, hash: 88 },
        { key: 'key-d', pct: 50, expected: true, hash: 21 },
        { key: 'key-e', pct: 50, expected: true, hash: 2 },
        { key: 'user-1', pct: 50, expected: true, hash: 0 },
        { key: 'user-2', pct: 50, expected: false, hash: 57 },
        { key: 'user-3', pct: 50, expected: true, hash: 38 },
        { key: 'key-a', pct: 27, expected: true, hash: 26 },
        { key: 'key-a', pct: 26, expected: false, hash: 26 },
        { key: 'key-c', pct: 89, expected: true, hash: 88 },
        { key: 'key-c', pct: 88, expected: false, hash: 88 },
    ])('routes "$key" (hash=$hash) to secondary=$expected at $pct%', ({ key, pct, expected, hash }) => {
        expect(keyHashBucket(Buffer.from(key))).toBe(hash)
        expect(shouldRouteToSecondary(Buffer.from(key), pct)).toBe(expected)
    })
})
