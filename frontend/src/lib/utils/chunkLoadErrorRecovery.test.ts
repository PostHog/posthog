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

    it('detects webpack chunk load errors', () => {
        const error = new Error('Loading chunk 123 failed.')
        error.name = 'ChunkLoadError'

        expect(isChunkLoadError(error)).toBe(true)
    })

    it('detects esbuild dynamic import failures', () => {
        expect(
            isChunkLoadError(new Error('Failed to fetch dynamically imported module: /static/chunk-123.js'))
        ).toBe(true)
    })

    it('ignores unrelated errors', () => {
        expect(isChunkLoadError(new Error('TypeError: cannot read properties of undefined'))).toBe(false)
        expect(getChunkLoadRecoveryAction(new Error('TypeError: cannot read properties of undefined'))).toBe('ignore')
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
