import {
    CHUNK_LOAD_RELOAD_WINDOW_MS,
    clearChunkLoadReloadAttempt,
    getChunkLoadRecoveryAction,
    isChunkLoadError,
    markChunkLoadReloadAttempt,
} from './chunkLoadErrorRecovery'

describe('chunkLoadErrorRecovery', () => {
    beforeEach(() => {
        sessionStorage.clear()
        clearChunkLoadReloadAttempt()
    })

    it.each([
        {
            name: 'detects webpack chunk load errors',
            error: Object.assign(new Error('Loading chunk 123 failed.'), { name: 'ChunkLoadError' }),
            isChunkLoadErrorExpected: true,
            recoveryActionExpected: 'reload',
        },
        {
            name: 'detects esbuild dynamic import failures',
            error: new Error('Failed to fetch dynamically imported module: /static/chunk-123.js'),
            isChunkLoadErrorExpected: true,
            recoveryActionExpected: 'reload',
        },
        {
            name: 'ignores unrelated errors',
            error: new Error('TypeError: cannot read properties of undefined'),
            isChunkLoadErrorExpected: false,
            recoveryActionExpected: 'ignore',
        },
    ])('$name', ({ error, isChunkLoadErrorExpected, recoveryActionExpected }) => {
        expect(isChunkLoadError(error)).toBe(isChunkLoadErrorExpected)
        expect(getChunkLoadRecoveryAction(error)).toBe(recoveryActionExpected)
    })

    it('reloads on the first chunk load failure', () => {
        expect(getChunkLoadRecoveryAction(new Error('Failed to fetch dynamically imported module: /static/chunk.js'))).toBe(
            'reload'
        )
    })

    it('shows an error after a recent reload attempt', () => {
        const now = 200_000
        markChunkLoadReloadAttempt(now)

        expect(
            getChunkLoadRecoveryAction(
                new Error('Failed to fetch dynamically imported module: /static/chunk.js'),
                now + CHUNK_LOAD_RELOAD_WINDOW_MS - 1
            )
        ).toBe('show-error')
    })

    it('allows another reload after the cooldown window passes', () => {
        const now = 200_000
        markChunkLoadReloadAttempt(now)

        expect(
            getChunkLoadRecoveryAction(
                new Error('Failed to fetch dynamically imported module: /static/chunk.js'),
                now + CHUNK_LOAD_RELOAD_WINDOW_MS + 1
            )
        ).toBe('reload')
    })
})
