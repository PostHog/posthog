import { IngestBatchResponse, SerializedKafkaMessage } from '../ingestion/api/types'
import { IngestionApiServer } from './ingestion-api-server'

describe('IngestionApiServer', () => {
    let server: IngestionApiServer
    let pipeline: { feed: jest.Mock; next: jest.Mock }
    let stopSpy: jest.SpyInstance

    function makeMessage(): SerializedKafkaMessage {
        return { topic: 't', partition: 0, offset: 0, timestamp: 0, key: null, value: '{}', headers: {} }
    }

    function makeRes(): {
        status: (code: number) => { json: (body: IngestBatchResponse) => void }
        statusCode: () => number
        body: () => IngestBatchResponse
    } {
        const json = jest.fn()
        const status = jest.fn().mockReturnValue({ json })
        return {
            status,
            statusCode: () => status.mock.calls[0][0],
            body: () => json.mock.calls[0][0],
        }
    }

    function handle(res: ReturnType<typeof makeRes>): Promise<void> {
        const req = { body: { batch_id: 'b1', messages: [makeMessage()] } }
        return (server as any).handleIngestRequest(req, res)
    }

    function isHealthy(): { status: string } {
        return (server as any).isHealthy()
    }

    beforeEach(() => {
        server = new IngestionApiServer()
        pipeline = { feed: jest.fn(), next: jest.fn() }
        ;(server as any).joinedPipeline = pipeline
        ;(server as any).promiseScheduler = { schedule: jest.fn(), waitForAll: jest.fn().mockResolvedValue(undefined) }
        ;(server as any).hogTransformer = { processInvocationResults: jest.fn().mockResolvedValue(undefined) }
        // stop() would call process.exit; stub it so the test only observes that it was invoked.
        stopSpy = jest.spyOn(server, 'stop').mockResolvedValue(undefined)
    })

    it('reports healthy before any failure', () => {
        expect(isHealthy().status).toBe('ok')
    })

    it('crashes and rebuilds on an unexpected pipeline error', async () => {
        pipeline.feed.mockResolvedValue({ ok: true })
        pipeline.next.mockRejectedValue(new Error('pipeline poisoned'))

        const res = makeRes()
        await handle(res)

        // Retriable 500 so the Rust consumer redelivers the batch.
        expect(res.statusCode()).toBe(500)
        expect(res.body()).toMatchObject({ status: 'error' })
        // Latched unhealthy and shut down so the supervisor rebuilds the pipeline.
        expect(isHealthy().status).toBe('error')
        expect(stopSpy).toHaveBeenCalledTimes(1)
    })

    it('returns 503 backpressure at capacity without crashing', async () => {
        pipeline.feed.mockResolvedValue({ ok: false, kind: 'at_capacity', reason: 'at concurrent batch capacity (1)' })

        const res = makeRes()
        await handle(res)

        expect(res.statusCode()).toBe(503)
        expect(isHealthy().status).toBe('ok')
        expect(stopSpy).not.toHaveBeenCalled()
        expect(pipeline.next).not.toHaveBeenCalled()
    })

    it('processes a successful batch and stays healthy', async () => {
        pipeline.feed.mockResolvedValue({ ok: true })
        pipeline.next.mockResolvedValue(null)

        const res = makeRes()
        await handle(res)

        expect(res.statusCode()).toBe(200)
        expect(res.body()).toMatchObject({ status: 'ok', accepted: 1 })
        expect(isHealthy().status).toBe('ok')
        expect(stopSpy).not.toHaveBeenCalled()
    })
})
