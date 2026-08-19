import { registerChunkReloadAttempt, resetChunkReloadGuard } from './chunkReloadGuard'

describe('chunkReloadGuard', () => {
    beforeEach(() => {
        window.localStorage.clear()
    })

    it('reloads on the first attempt and surfaces on the next one in the same cycle', () => {
        const now = 1_000_000
        expect(registerChunkReloadAttempt(now, 'scene').shouldReload).toBe(true)
        // 30s later - past a 20s gap but still one slow reload cycle - must not reload again
        expect(registerChunkReloadAttempt(now + 30_000, 'scene').shouldReload).toBe(false)
    })

    it('treats an attempt after the window as a fresh cycle', () => {
        const now = 1_000_000
        registerChunkReloadAttempt(now, 'scene')
        expect(registerChunkReloadAttempt(now + 200_000, 'scene').shouldReload).toBe(true)
    })

    it('reload is allowed again after a successful load resets the guard', () => {
        const now = 1_000_000
        registerChunkReloadAttempt(now, 'scene')
        resetChunkReloadGuard('scene')
        expect(registerChunkReloadAttempt(now + 5_000, 'scene').shouldReload).toBe(true)
    })

    it('resetting one scope leaves the other scope counting, so a lazy chunk still trips its guard', () => {
        const now = 1_000_000
        // A lazy descendant failed once and reloaded.
        expect(registerChunkReloadAttempt(now, 'lazy').shouldReload).toBe(true)
        // The scene chunk then loads on the next page load and clears its own counter.
        resetChunkReloadGuard('scene')
        // The lazy descendant fails again within the window: it must surface, not reload forever.
        expect(registerChunkReloadAttempt(now + 5_000, 'lazy').shouldReload).toBe(false)
    })
})
