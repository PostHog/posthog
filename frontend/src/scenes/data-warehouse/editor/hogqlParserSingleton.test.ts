// Parsing is a synchronous WASM call over the whole query — roughly 36ms per 1000 characters, so
// seconds on a long one. These cover the memoization that keeps it off the main thread when the
// text has not changed: without it, every cursor move in a long query re-parses the whole document
// and freezes the editor, and the decoration and table/column pipelines each pay for their own
// parse of the same text one debounce apart.
const parseSelectMock = jest.fn()
const initMock = jest.fn()

jest.mock('@posthog/hogql-parser', () => ({
    __esModule: true,
    default: () => {
        initMock()
        return Promise.resolve({ parseSelect: parseSelectMock })
    },
}))

describe('hogqlParserSingleton', () => {
    let parseSelect: (input: string, isInternal?: boolean) => Promise<string>

    beforeEach(async () => {
        jest.resetModules()
        parseSelectMock.mockReset()
        initMock.mockReset()
        parseSelectMock.mockImplementation((input: string) => `{"node":"SelectQuery","len":${input.length}}`)
        ;({ parseSelect } = await import('./hogqlParserSingleton'))
    })

    it('parses identical text once, however many times it is asked', async () => {
        // The cursor-move case: the editor re-requests a parse on every arrow key.
        const results = []
        for (let i = 0; i < 5; i++) {
            results.push(await parseSelect('SELECT 1 FROM events'))
        }

        expect(parseSelectMock).toHaveBeenCalledTimes(1)
        expect(new Set(results).size).toBe(1)
    })

    it('shares one parse between callers that ask while it is still running', async () => {
        // The decoration and table/column pipelines are ~50ms apart, far less than a long parse,
        // so the second caller arrives mid-flight. Caching resolved values alone would miss this.
        let release: (value: string) => void = () => {}
        parseSelectMock.mockImplementation(() => new Promise<string>((resolve) => (release = resolve)))

        const first = parseSelect('SELECT 1 FROM events')
        const second = parseSelect('SELECT 1 FROM events')
        // Both calls have to get past awaiting parser init before the underlying parse starts.
        await new Promise((resolve) => setTimeout(resolve, 0))
        release('{"node":"SelectQuery"}')

        expect(await first).toBe('{"node":"SelectQuery"}')
        expect(await second).toBe('{"node":"SelectQuery"}')
        expect(parseSelectMock).toHaveBeenCalledTimes(1)
        expect(initMock).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['different text', 'SELECT 2 FROM events', undefined],
        ['the same text with a different isInternal', 'SELECT 1 FROM events', true],
    ])('parses again for %s', async (_label, input, isInternal) => {
        await parseSelect('SELECT 1 FROM events')
        await parseSelect(input, isInternal)

        expect(parseSelectMock).toHaveBeenCalledTimes(2)
    })

    it('retries after a failed parse instead of caching the rejection', async () => {
        parseSelectMock.mockRejectedValueOnce(new Error('boom'))

        await expect(parseSelect('SELECT 1 FROM events')).rejects.toThrow('boom')
        await expect(parseSelect('SELECT 1 FROM events')).resolves.toContain('SelectQuery')
        expect(parseSelectMock).toHaveBeenCalledTimes(2)
    })

    it('does not grow without bound as the query is edited', async () => {
        // Each cached entry retains the query text and an AST JSON roughly 12x its size, so the
        // cache has to forget old revisions rather than accumulate one per keystroke.
        for (let i = 0; i < 40; i++) {
            await parseSelect(`SELECT ${i} FROM events`)
        }
        // The oldest revision must have been evicted, so asking for it again re-parses.
        await parseSelect('SELECT 0 FROM events')

        expect(parseSelectMock).toHaveBeenCalledTimes(41)
    })
})
