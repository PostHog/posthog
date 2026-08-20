import { CrawlHistory, CrawlHistoryRedis, CrawlHistoryRedisPool } from './crawl-history'

/** Above one round trip's key limit, so every test crosses a chunk boundary. */
const KEYS = Array.from({ length: 600 }, (_value, index) => `k${index}`)
const NOW_MS = 1_700_000_000_000

type ExecResult = [Error | null, unknown][] | null

class FakeClient implements CrawlHistoryRedis {
    public readonly pipelined: string[] = []
    constructor(
        private readonly behavior: {
            mget?: (keys: string[]) => (string | null)[] | Promise<(string | null)[]>
            exec?: (keys: string[]) => ExecResult
        }
    ) {}

    mget(...keys: string[]): Promise<(string | null)[]> {
        return Promise.resolve(this.behavior.mget?.(keys) ?? keys.map(() => null))
    }

    pipeline(): { set: (key: string) => void; exec: () => Promise<ExecResult> } {
        const keys: string[] = []
        return {
            set: (key: string) => {
                keys.push(key)
                this.pipelined.push(key)
            },
            exec: () =>
                Promise.resolve(
                    'exec' in this.behavior ? this.behavior.exec!(keys) : keys.map(() => [null, 'OK'] as [null, string])
                ),
        }
    }
}

function poolOf(client: FakeClient): CrawlHistoryRedisPool {
    return {
        acquire: () => Promise.resolve(client),
        release: () => Promise.resolve(),
        destroy: () => Promise.resolve(),
    }
}

describe('CrawlHistory', () => {
    const build = (client: FakeClient, budgetMs = 60_000): CrawlHistory =>
        new CrawlHistory(poolOf(client), 1_000, budgetMs)

    it('reports the index of every key that exists, across chunk boundaries', async () => {
        // The caller maps these indexes back onto its own candidate list, so an off-by-one skips the
        // wrong URL and nothing reports it.
        const present = new Set(['k0', 'k255', 'k256', 'k599'])
        const client = new FakeClient({ mget: (keys) => keys.map((key) => (present.has(key) ? '{}' : null)) })

        const result = await build(client).read(KEYS, NOW_MS)

        expect([...result.known].sort((a, b) => a - b)).toEqual([0, 255, 256, 599])
        expect(result.failed.size).toBe(0)
    })

    it('reports the index of every key in a chunk that threw, rather than calling them absent', async () => {
        const client = new FakeClient({
            mget: (keys) => {
                if (keys.includes('k256')) {
                    throw new Error('redis down')
                }
                return keys.map(() => null)
            },
        })

        const result = await build(client).read(KEYS, NOW_MS)

        // The caller drops these rather than fetches them, so it needs which keys, not how many.
        expect(result.failed.size).toBe(256)
        expect(result.failed.has(256)).toBe(true)
        expect(result.failed.has(255)).toBe(false)
        expect(result.known.size).toBe(0)
    })

    it('reports the index of a single command that failed inside a write pipeline', async () => {
        const client = new FakeClient({
            exec: (keys) => keys.map((key) => (key === 'k300' ? [new Error('nope'), null] : [null, 'OK'])),
        })

        const { failed } = await build(client).record(KEYS, 1, 60)

        expect([...failed]).toEqual([300])
    })

    it('treats a pipeline that answers with nothing as a whole failed chunk', async () => {
        const client = new FakeClient({ exec: () => null })

        const { failed } = await build(client).record(KEYS, 1, 60)

        expect(failed.size).toBe(KEYS.length)
    })

    it('stops issuing round trips once the batch budget is spent', async () => {
        // A batch that runs past the heartbeat restarts the pod onto the same offsets, so the lane
        // sheds the rest of the work instead.
        const client = new FakeClient({
            mget: async (keys) => {
                await new Promise((resolve) => setTimeout(resolve, 20))
                return keys.map(() => null)
            },
        })

        const result = await build(client, 30).read(KEYS, NOW_MS)

        expect(result.failed.size).toBeGreaterThan(0)
    })

    it('writes every key exactly once', async () => {
        const client = new FakeClient({})

        await build(client).record(KEYS, 1, 60)

        expect(client.pipelined).toEqual(KEYS)
    })
})
