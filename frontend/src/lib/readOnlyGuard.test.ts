import { ApiError } from 'lib/api-error'
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
                ['file system log view', 'POST', '/api/environments/2/file_system/log_view/'],
                ['log view with query string', 'POST', '/api/environments/2/file_system/log_view/?foo=bar'],
                ['insights viewed (no trailing slash)', 'POST', '/api/environments/2/insights/viewed'],
                ['insights viewed with trailing slash', 'POST', '/api/environments/2/insights/viewed/'],
                ['insights viewed with query string', 'POST', '/api/environments/2/insights/viewed/?foo=bar'],
                ['insights timing (no trailing slash)', 'POST', '/api/projects/2/insights/timing'],
                ['insights timing with trailing slash', 'POST', '/api/projects/2/insights/timing/'],
                ['metalytics (no trailing slash)', 'POST', '/api/projects/2/metalytics'],
                ['metalytics with trailing slash', 'POST', '/api/projects/2/metalytics/'],
                ['new AI conversation', 'POST', '/api/environments/2/conversations'],
                ['new AI conversation with trailing slash', 'POST', '/api/environments/2/conversations/'],
                ['AI conversation by id', 'PATCH', '/api/environments/2/conversations/abc-123/'],
                ['AI conversation delete', 'DELETE', '/api/environments/2/conversations/abc-123/'],
                ['AI conversation queue', 'POST', '/api/environments/2/conversations/abc-123/queue'],
                ['AI conversation queue clear', 'POST', '/api/environments/2/conversations/abc-123/queue/clear'],
                ['AI conversation append message', 'POST', '/api/environments/2/conversations/abc-123/append_message'],
                ['AI conversation cancel', 'PATCH', '/api/environments/2/conversations/abc-123/cancel/'],
            ] as const)('lets %s through (%s %s)', (_label, method, url) => {
                const notifier = jest.fn()
                setReadOnlyNotifier(notifier)
                expect(() => assertNotReadOnly(method, url)).not.toThrow()
                expect(notifier).not.toHaveBeenCalled()
            })

            it.each([
                ['endpoint that just contains the word query in a name', 'POST', '/api/environments/2/queryless/'],
                ['similar prefix without slash', 'POST', '/api/environments/2/queryteam/'],
                ['file system entity write blocked', 'POST', '/api/environments/2/file_system/'],
                ['file system non-log_view blocked', 'POST', '/api/environments/2/file_system/abc-123/move'],
                ['insight create blocked', 'POST', '/api/environments/2/insights/'],
                ['insight non-viewed sub-action blocked', 'POST', '/api/environments/2/insights/123/viewed_by'],
                ['insight non-timing sub-action blocked', 'POST', '/api/environments/2/insights/123/timing_breakdown'],
                ['metalytics-like prefix blocked', 'POST', '/api/projects/2/metalyticsfoo/'],
                ['ticket saved views write blocked', 'POST', '/api/environments/2/conversations/views/'],
                [
                    'ticket saved views write blocked (no trailing slash)',
                    'POST',
                    '/api/environments/2/conversations/views',
                ],
                ['ticket saved view detail write blocked', 'PATCH', '/api/environments/2/conversations/views/abc/'],
                ['support tickets write blocked (under projects)', 'POST', '/api/projects/2/conversations/tickets/'],
                [
                    'support tickets write blocked (under environments)',
                    'POST',
                    '/api/environments/2/conversations/tickets/',
                ],
                ['conversations-like prefix blocked', 'POST', '/api/environments/2/conversationsfoo/'],
            ] as const)('still blocks %s (%s %s) — only allowlisted paths pass', (_l, method, url) => {
                expect(() => assertNotReadOnly(method, url)).toThrow(ReadOnlyModeError)
            })
        })
    })

    describe('ReadOnlyModeError', () => {
        it('is an ApiError so existing catch blocks surface its detail', () => {
            const err = new ReadOnlyModeError('POST')
            expect(err).toBeInstanceOf(ApiError)
            expect(err.status).toBe(403)
            expect(err.code).toBe('read_only_blocked')
            expect(err.name).toBe('ReadOnlyModeError')
        })

        it.each([
            ['POST', 'create'],
            ['PUT', 'edit'],
            ['PATCH', 'edit'],
            ['DELETE', 'delete'],
        ] as const)('personalises the detail for %s (verb: %s)', (method, verb) => {
            const err = new ReadOnlyModeError(method)
            expect(err.detail).toBe(
                `Read-only mode is on — that ${verb} was blocked. Ask Max or the MCP to make the change for you.`
            )
        })

        it('falls back to a generic detail when constructed without a method', () => {
            const err = new ReadOnlyModeError()
            expect(err.detail).toContain('that change was blocked')
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
