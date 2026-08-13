import { SightingRedis, SightingRedisPool, UrlSightings } from './url-sightings'

/** Above one round trip's key limit, so every test crosses a chunk boundary. */
const KEYS = Array.from({ length: 600 }, (_value, index) => `k${index}`)

type ExecResult = [Error | null, unknown][] | null

class FakeClient implements SightingRedis {
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

function poolOf(client: FakeClient): SightingRedisPool {
    return {
        acquire: () => Promise.resolve(client),
        release: () => Promise.resolve(),
        destroy: () => Promise.resolve(),
    }
}

describe('UrlSightings', () => {
    const build = (client: FakeClient, budgetMs = 60_000): UrlSightings =>
        new UrlSightings(poolOf(client), 1_000, budgetMs)

    it('reports the index of every key that exists, across chunk boundaries', async () => {
        // The one place a silent mistake is possible: the caller maps these indexes back onto its
        // own candidate list, so an off-by-one skips the wrong URL and nothing surfaces it.
        const present = new Set(['k0', 'k255', 'k256', 'k599'])
        const client = new FakeClient({ mget: (keys) => keys.map((key) => (present.has(key) ? '{}' : null)) })

        const result = await build(client).read(KEYS)

        expect([...result.known].sort((a, b) => a - b)).toEqual([0, 255, 256, 599])
        expect(result.failed).toBe(0)
    })

    it('counts a chunk that throws as failed rather than as absent', async () => {
        const client = new FakeClient({
            mget: (keys) => {
                if (keys.includes('k256')) {
                    throw new Error('redis down')
                }
                return keys.map(() => null)
            },
        })

        const result = await build(client).read(KEYS)

        expect(result.failed).toBe(256)
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
        // A batch that outruns the heartbeat gets the pod restarted onto the same offsets, so the
        // lane sheds the rest of the work instead.
        const client = new FakeClient({
            mget: async (keys) => {
                await new Promise((resolve) => setTimeout(resolve, 20))
                return keys.map(() => null)
            },
        })

        const result = await build(client, 30).read(KEYS)

        expect(result.failed).toBeGreaterThan(0)
    })

    it('writes every key exactly once', async () => {
        const client = new FakeClient({})

        await build(client).record(KEYS, 1, 60)

        expect(client.pipelined).toEqual(KEYS)
    })
})
