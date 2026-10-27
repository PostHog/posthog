import { FingerprintedLoader } from './fingerprinted-loader'

type Row = { id: string; body: string }

describe('FingerprintedLoader', () => {
    let db: Record<string, { body: string; fingerprint: string }>
    let cache: Record<string, Row | null>
    let fetchFingerprints: jest.Mock
    let fetchFull: jest.Mock
    let loader: FingerprintedLoader<Row>

    const load = async (ids: string[]): Promise<Record<string, Row | undefined>> => {
        const result = await loader.load(ids)
        for (const id of ids) {
            cache[id] = result[id] ?? null
        }
        return result
    }

    beforeEach(() => {
        db = {
            a: { body: 'a1', fingerprint: 'fa1' },
            b: { body: 'b1', fingerprint: 'fb1' },
        }
        cache = {}
        fetchFingerprints = jest.fn((ids: string[]) =>
            Promise.resolve(Object.fromEntries(ids.filter((id) => db[id]).map((id) => [id, db[id].fingerprint])))
        )
        fetchFull = jest.fn((ids: string[]) =>
            Promise.resolve(
                Object.fromEntries(
                    ids
                        .filter((id) => db[id])
                        .map((id) => [id, { value: { id, body: db[id].body }, fingerprint: db[id].fingerprint }])
                )
            )
        )
        loader = new FingerprintedLoader<Row>({
            name: 'test',
            peek: (id) => cache[id],
            fetchFingerprints,
            fetchFull,
        })
    })

    it('fetches full rows when nothing is cached', async () => {
        const result = await load(['a', 'b'])
        expect(result).toEqual({ a: { id: 'a', body: 'a1' }, b: { id: 'b', body: 'b1' } })
        expect(fetchFingerprints).not.toHaveBeenCalled()
        expect(fetchFull).toHaveBeenCalledWith(['a', 'b'])
    })

    it('reuses cached rows whose fingerprint is unchanged and refetches only changed ones', async () => {
        const first = await load(['a', 'b'])
        fetchFull.mockClear()

        db.b = { body: 'b2', fingerprint: 'fb2' }
        const second = await load(['a', 'b'])

        expect(fetchFingerprints).toHaveBeenCalledWith(['a', 'b'])
        expect(fetchFull).toHaveBeenCalledWith(['b'])
        expect(second.a).toBe(first.a)
        expect(second.b).toEqual({ id: 'b', body: 'b2' })
    })

    it('does no full fetch when nothing changed', async () => {
        await load(['a', 'b'])
        fetchFull.mockClear()

        await load(['a', 'b'])
        expect(fetchFull).not.toHaveBeenCalled()
    })

    it('drops rows that no longer match', async () => {
        await load(['a', 'b'])
        delete db.a
        const result = await load(['a', 'b'])
        expect(result.a).toBeUndefined()
        expect(result.b).toEqual({ id: 'b', body: 'b1' })
    })

    it('does a full fetch for ids passed to forceFullReload, once', async () => {
        await load(['a', 'b'])
        fetchFull.mockClear()

        loader.forceFullReload(['a'])
        await load(['a', 'b'])
        expect(fetchFull).toHaveBeenCalledWith(['a'])
        expect(fetchFingerprints).toHaveBeenCalledWith(['b'])

        fetchFull.mockClear()
        await load(['a', 'b'])
        expect(fetchFull).not.toHaveBeenCalled()
    })

    it('keeps the forced full fetch when the load fails', async () => {
        await load(['a'])
        loader.forceFullReload(['a'])
        fetchFull.mockRejectedValueOnce(new Error('pgbouncer blip'))
        await expect(load(['a'])).rejects.toThrow('pgbouncer blip')

        fetchFull.mockClear()
        await load(['a'])
        expect(fetchFull).toHaveBeenCalledWith(['a'])
    })

    it('does a full fetch when the cached value was evicted', async () => {
        await load(['a'])
        delete cache.a
        fetchFull.mockClear()

        await load(['a'])
        expect(fetchFingerprints).not.toHaveBeenCalled()
        expect(fetchFull).toHaveBeenCalledWith(['a'])
    })
})
