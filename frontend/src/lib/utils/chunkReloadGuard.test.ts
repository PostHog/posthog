import { registerChunkReloadAttempt, resetChunkReloadGuard } from './chunkReloadGuard'

describe('chunkReloadGuard', () => {
    beforeEach(() => {
        window.localStorage.clear()
    })

    it('reloads on the first attempt and surfaces on the next one in the same cycle', () => {
        const now = 1_000_000
        expect(registerChunkReloadAttempt(now).shouldReload).toBe(true)
        // 30s later - past a 20s gap but still one slow reload cycle - must not reload again
        expect(registerChunkReloadAttempt(now + 30_000).shouldReload).toBe(false)
    })

    it('treats an attempt after the window as a fresh cycle', () => {
        const now = 1_000_000
        registerChunkReloadAttempt(now)
        expect(registerChunkReloadAttempt(now + 200_000).shouldReload).toBe(true)
    })

    it('reload is allowed again after a successful load resets the guard', () => {
        const now = 1_000_000
        registerChunkReloadAttempt(now)
        resetChunkReloadGuard()
        expect(registerChunkReloadAttempt(now + 5_000).shouldReload).toBe(true)
    })
})
