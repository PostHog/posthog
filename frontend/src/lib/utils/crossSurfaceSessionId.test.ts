import { consumeCrossSurfaceSessionId, POSTHOG_SESSION_ID_URL_PARAM } from 'lib/utils/crossSurfaceSessionId'

function uuidV7At(timestampMs: number): string {
    const ts = Math.floor(timestampMs).toString(16).padStart(12, '0')
    return `${ts.slice(0, 8)}-${ts.slice(8, 12)}-7123-8abc-0123456789ab`
}

describe('consumeCrossSurfaceSessionId', () => {
    let replaceStateSpy: jest.SpyInstance

    beforeEach(() => {
        replaceStateSpy = jest.spyOn(window.history, 'replaceState')
    })

    afterEach(() => {
        replaceStateSpy.mockRestore()
        window.history.replaceState(null, '', '/')
    })

    it('returns a valid recent session ID and strips only that param', () => {
        const sessionId = uuidV7At(Date.now() - 60_000)
        window.history.replaceState(
            null,
            '',
            `/insights?${POSTHOG_SESSION_ID_URL_PARAM}=${sessionId}&kept=1#panel=activity`
        )
        replaceStateSpy.mockClear()

        expect(consumeCrossSurfaceSessionId()).toEqual(sessionId)
        expect(window.location.search).toEqual('?kept=1')
        expect(window.location.pathname).toEqual('/insights')
        expect(window.location.hash).toEqual('#panel=activity')
    })

    it.each([
        ['plain garbage', 'not-a-uuid'],
        ['UUIDv4', '9b0813c0-b661-4f47-92ca-1e0890a3a8c4'],
        ['wrong variant nibble', uuidV7At(Date.now()).replace('-8abc-', '-cabc-')],
        ['right shape but non-hex characters', 'zzzzzzzz-zzzz-7zzz-8zzz-zzzzzzzzzzzz'],
        ['older than 24h', uuidV7At(Date.now() - 25 * 60 * 60 * 1000)],
        ['future-dated beyond clock skew', uuidV7At(Date.now() + 10 * 60 * 1000)],
    ])('rejects %s but still strips the param', (_name, value) => {
        window.history.replaceState(null, '', `/insights?${POSTHOG_SESSION_ID_URL_PARAM}=${value}`)

        expect(consumeCrossSurfaceSessionId()).toBeNull()
        expect(window.location.search).toEqual('')
    })

    it('does not touch history when the param is absent', () => {
        window.history.replaceState(null, '', '/insights?kept=1')
        replaceStateSpy.mockClear()

        expect(consumeCrossSurfaceSessionId()).toBeNull()
        expect(replaceStateSpy).not.toHaveBeenCalled()
        expect(window.location.search).toEqual('?kept=1')
    })
})
