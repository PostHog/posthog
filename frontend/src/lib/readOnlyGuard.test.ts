import {
    assertNotReadOnly,
    isReadOnly,
    ReadOnlyModeError,
    setReadOnlyGetter,
    setReadOnlyNotifier,
} from 'lib/readOnlyGuard'

describe('readOnlyGuard', () => {
    afterEach(() => {
        // Tear down module-level state so each test starts from a clean slate.
        setReadOnlyGetter(null)
        setReadOnlyNotifier(null)
    })

    describe('isReadOnly()', () => {
        it('returns false when no getter is registered', () => {
            expect(isReadOnly()).toBe(false)
        })

        it.each([
            ['getter returns true', true, true],
            ['getter returns false', false, false],
        ])('reflects the registered getter when %s', (_label, getterReturn, expected) => {
            setReadOnlyGetter(() => getterReturn)
            expect(isReadOnly()).toBe(expected)
        })
    })

    describe('assertNotReadOnly()', () => {
        describe('when not in read-only mode', () => {
            it.each([
                ['POST', '/api/environments/2/dashboards/'],
                ['PATCH', '/api/environments/2/dashboards/1/'],
                ['PUT', '/api/environments/2/dashboards/1/'],
                ['DELETE', '/api/environments/2/dashboards/1/'],
                ['POST', '/api/environments/2/query/'],
            ] as const)('lets %s %s through silently', (method, url) => {
                setReadOnlyGetter(() => false)
                const notifier = jest.fn()
                setReadOnlyNotifier(notifier)

                expect(() => assertNotReadOnly(method, url)).not.toThrow()
                expect(notifier).not.toHaveBeenCalled()
            })
        })

        describe('when in read-only mode', () => {
            beforeEach(() => {
                setReadOnlyGetter(() => true)
            })

            it.each([
                ['POST', '/api/environments/2/dashboards/'],
                ['PATCH', '/api/environments/2/dashboards/1/'],
                ['PUT', '/api/environments/2/dashboards/1/'],
                ['DELETE', '/api/environments/2/dashboards/1/'],
            ] as const)('blocks %s %s with a ReadOnlyModeError', (method, url) => {
                expect(() => assertNotReadOnly(method, url)).toThrow(ReadOnlyModeError)
            })

            it('calls the notifier with the blocked method', () => {
                const notifier = jest.fn()
                setReadOnlyNotifier(notifier)
                expect(() => assertNotReadOnly('POST', '/api/environments/2/dashboards/')).toThrow(ReadOnlyModeError)
                expect(notifier).toHaveBeenCalledTimes(1)
                expect(notifier).toHaveBeenCalledWith('POST')
            })

            it('does not throw when no notifier is registered', () => {
                // Notifier is optional — guard should still block but stay quiet.
                expect(() => assertNotReadOnly('POST', '/api/environments/2/dashboards/')).toThrow(ReadOnlyModeError)
            })

            // Reads-disguised-as-writes (e.g. HogQL/trends/funnels via POST to /query/)
            // must pass through even in read-only mode — otherwise the app becomes
            // unusable.
            it.each([
                ['plain query', 'POST', '/api/environments/2/query/'],
                ['query with id', 'POST', '/api/environments/2/query/abc-123/'],
                ['query upgrade', 'POST', '/api/environments/2/query/upgrade'],
                ['query log', 'POST', '/api/environments/2/query/abc-123/log'],
                ['query with trailing query string', 'POST', '/api/environments/2/query/?refresh=true'],
                ['delete on query path', 'DELETE', '/api/environments/2/query/abc-123/'],
                ['insights timing telemetry', 'POST', '/api/projects/2/insights/timing'],
                ['insights timing with trailing slash', 'POST', '/api/projects/2/insights/timing/'],
                ['insights timing with query string', 'POST', '/api/projects/2/insights/timing?foo=bar'],
            ] as const)('lets %s through (%s %s)', (_label, method, url) => {
                const notifier = jest.fn()
                setReadOnlyNotifier(notifier)
                expect(() => assertNotReadOnly(method, url)).not.toThrow()
                expect(notifier).not.toHaveBeenCalled()
            })

            it.each([
                ['endpoint that just contains the word query in a name', 'POST', '/api/environments/2/queryless/'],
                ['similar prefix without slash', 'POST', '/api/environments/2/queryteam/'],
                ['insights endpoint that is not timing', 'POST', '/api/projects/2/insights/'],
                ['insights timing prefix match without slash', 'POST', '/api/projects/2/insights/timings/'],
            ] as const)('still blocks %s (%s %s) — only exact allow-list paths pass through', (_l, method, url) => {
                expect(() => assertNotReadOnly(method, url)).toThrow(ReadOnlyModeError)
            })
        })
    })

    describe('ReadOnlyModeError', () => {
        it('has a sensible default detail message so caller error-fallback patterns produce truthful toasts', () => {
            const err = new ReadOnlyModeError()
            expect(err.detail).toBe('Read-only mode is on — change blocked. Use Max or the MCP to make this change.')
            expect(err.name).toBe('ReadOnlyModeError')
        })

        it('accepts a custom message', () => {
            const err = new ReadOnlyModeError('custom message')
            expect(err.message).toBe('custom message')
        })
    })

    describe('setReadOnlyGetter', () => {
        let warnSpy: jest.SpyInstance

        beforeEach(() => {
            warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => undefined)
        })

        afterEach(() => {
            warnSpy.mockRestore()
        })

        it('warns when overwriting an existing getter (double-mount detection)', () => {
            setReadOnlyGetter(() => true)
            setReadOnlyGetter(() => false)
            expect(warnSpy).toHaveBeenCalledTimes(1)
            expect(warnSpy.mock.calls[0][0]).toContain('setReadOnlyGetter')
        })

        it('does not warn when clearing the getter', () => {
            setReadOnlyGetter(() => true)
            setReadOnlyGetter(null)
            expect(warnSpy).not.toHaveBeenCalled()
        })

        it('does not warn on first registration', () => {
            setReadOnlyGetter(() => true)
            expect(warnSpy).not.toHaveBeenCalled()
        })
    })
})
