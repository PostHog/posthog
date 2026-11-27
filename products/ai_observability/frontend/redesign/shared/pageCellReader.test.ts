import { CellLoads, withFailed, withLoaded, withRequested } from './cellLoads'
import { CellEntry, PageCellReader, createPageCellReader } from './pageCellReader'

interface Params {
    date_from: string
}

interface PendingRead {
    keys: string[]
    params: Params
    signal: AbortSignal
    answer: (value: string) => void
    fail: () => void
}

/** The part of kea-disposables the reader uses, with an unmount that runs every cleanup. */
function fakeDisposables(): {
    isDisposed: boolean
    add: (setup: () => () => void, key: string) => void
    unmount: () => void
} {
    const cleanups = new Map<string, () => void>()
    const disposables = {
        isDisposed: false,
        add: (setup: () => () => void, key: string): void => {
            cleanups.get(key)?.()
            cleanups.set(key, setup())
        },
        unmount: (): void => {
            cleanups.forEach((cleanup) => cleanup())
            disposables.isDisposed = true
        },
    }
    return disposables
}

const LAST_WEEK: Params = { date_from: '-7d' }
const LAST_DAY: Params = { date_from: '-24h' }

describe('createPageCellReader', () => {
    let loads: CellLoads<string>
    let reads: PendingRead[]
    let failures: string[][]
    let reader: PageCellReader<Params>
    let disposables: ReturnType<typeof fakeDisposables>

    const valueOf = (key: string): string | undefined => {
        const load = loads.get(key)
        return load?.status === 'ready' ? load.value : load?.status
    }

    beforeEach(() => {
        loads = new Map()
        reads = []
        failures = []
        disposables = fakeDisposables()
        reader = createPageCellReader<Params, string>({
            cache: { disposables },
            loads: () => loads,
            paramsChanged: () => {
                loads = new Map()
            },
            requested: (keys) => {
                loads = withRequested(loads, keys)
            },
            failed: (keys) => {
                failures.push(keys)
                loads = withFailed(loads, keys)
            },
            loaded: (entries) => {
                loads = withLoaded(loads, entries)
            },
            request: (keys, params, signal) =>
                new Promise<CellEntry<string>[]>((resolve, reject) => {
                    reads.push({
                        keys,
                        params,
                        signal,
                        answer: (value) => resolve(keys.map((key) => [key, value])),
                        fail: () => reject(new Error('read failed')),
                    })
                }),
        })
    })

    async function loadPage(keys: string[], value: string, params: Params = LAST_WEEK): Promise<void> {
        const read = reader.pageLoaded(keys, params)
        reads.at(-1)?.answer(value)
        await read
    }

    it('reads the keys of a page that have no value yet, with the params of the page', async () => {
        const read = reader.pageLoaded(['a', 'b'], LAST_WEEK)
        expect(reads.map(({ keys, params }) => ({ keys, params }))).toEqual([{ keys: ['a', 'b'], params: LAST_WEEK }])
        expect([valueOf('a'), valueOf('b')]).toEqual(['loading', 'loading'])

        reads[0].answer('first')
        await read
        await loadPage(['a', 'c'], 'second')

        expect(reads.map(({ keys }) => keys)).toEqual([['a', 'b'], ['c']])
        expect([valueOf('a'), valueOf('b'), valueOf('c')]).toEqual(['first', 'first', 'second'])
    })

    it('fails only the keys of the read that failed', async () => {
        await loadPage(['a'], 'first')

        const read = reader.pageLoaded(['a', 'b', 'c'], LAST_WEEK)
        reads[1].fail()
        await read

        expect(failures).toEqual([['b', 'c']])
        expect([valueOf('a'), valueOf('b'), valueOf('c')]).toEqual(['first', 'error', 'error'])
    })

    it.each<[string, (older: PendingRead) => void]>([
        ['answers', (older) => older.answer('older')],
        ['fails', (older) => older.fail()],
    ])(
        'keeps the latest reload when the reload before it %s last, and reports nothing for it',
        async (_name, settleOlder) => {
            await loadPage(['a'], 'first')
            reader.pageReloading()
            const olderRead = reader.pageLoaded(['a'], LAST_WEEK)
            reader.pageReloading()
            const newerRead = reader.pageLoaded(['a'], LAST_WEEK)

            reads[2].answer('newer')
            await newerRead
            settleOlder(reads[1])
            await olderRead

            expect(valueOf('a')).toEqual('newer')
            expect(failures).toEqual([])
        }
    )

    it.each<[string, (read: PendingRead) => void]>([
        ['an answer', (read) => read.answer('stale')],
        ['a failure', (read) => read.fail()],
    ])('drops %s for params that changed and then changed back', async (_name, settle) => {
        const staleRead = reader.pageLoaded(['a'], LAST_WEEK)
        reader.scopeTo(LAST_DAY)
        reader.scopeTo(LAST_WEEK)

        settle(reads[0])
        await staleRead

        expect(valueOf('a')).toBeUndefined()
        expect(failures).toEqual([])
        await loadPage(['a'], 'fresh')
        expect(reads.map(({ keys, params }) => ({ keys, params }))).toEqual([
            { keys: ['a'], params: LAST_WEEK },
            { keys: ['a'], params: LAST_WEEK },
        ])
        expect(valueOf('a')).toEqual('fresh')
    })

    it('asks again on a reload for keys whose first read is still in flight, and keeps the newer answer', async () => {
        const firstRead = reader.pageLoaded(['a'], LAST_WEEK)
        reader.pageReloading()
        const reload = reader.pageLoaded(['a'], LAST_WEEK)

        reads[1].answer('reloaded')
        await reload
        reads[0].answer('first')
        await firstRead

        expect(reads.map(({ keys }) => keys)).toEqual([['a'], ['a']])
        expect(valueOf('a')).toEqual('reloaded')
    })

    it.each<[string, () => void]>([
        ['its params change', () => reader.scopeTo(LAST_DAY)],
        ['the logic unmounts', () => disposables.unmount()],
    ])('aborts the reads in flight when %s', (_name, discard) => {
        void reader.pageLoaded(['a'], LAST_WEEK)
        void reader.read(['b'], LAST_WEEK)

        discard()

        expect(reads.map(({ signal }) => signal.aborted)).toEqual([true, true])
    })

    it('keeps the reads of the current params open', () => {
        void reader.pageLoaded(['a'], LAST_WEEK)
        reader.scopeTo(LAST_DAY)
        void reader.read(['b'], LAST_DAY)

        expect(reads.map(({ signal }) => signal.aborted)).toEqual([true, false])
    })
})
