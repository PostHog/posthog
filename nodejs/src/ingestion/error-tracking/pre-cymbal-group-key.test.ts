import { createTestPluginEvent } from '~/tests/helpers/plugin-event'

import { preCymbalGroupKey } from './pre-cymbal-group-key'

const exceptionEvent = (exception: Record<string, unknown>) =>
    createTestPluginEvent({ properties: { $exception_list: [exception] } })

describe('preCymbalGroupKey', () => {
    it('returns null when $exception_list is missing', () => {
        expect(preCymbalGroupKey(createTestPluginEvent())).toBeNull()
    })

    it('returns null when there is no message and no frames', () => {
        expect(preCymbalGroupKey(exceptionEvent({ type: 'Error' }))).toBeNull()
    })

    it('returns a 16-char hex digest', () => {
        const key = preCymbalGroupKey(exceptionEvent({ type: 'Error', value: 'boom' }))
        expect(key).toMatch(/^[0-9a-f]{16}$/)
    })

    describe('message-only exceptions', () => {
        it('groups by type and value', () => {
            const a = preCymbalGroupKey(exceptionEvent({ type: 'TypeError', value: 'same' }))
            const b = preCymbalGroupKey(exceptionEvent({ type: 'TypeError', value: 'same' }))
            const c = preCymbalGroupKey(exceptionEvent({ type: 'TypeError', value: 'other' }))

            expect(a).toBe(b)
            expect(a).not.toBe(c)
        })
    })

    describe('stack exceptions', () => {
        const stackEvent = (fn: string, value: string = 'msg') =>
            exceptionEvent({
                type: 'TypeError',
                value,
                stacktrace: {
                    frames: [{ function: fn, filename: `${fn}.js`, lineno: 1 }],
                },
            })

        it('groups by stack and ignores message when frames exist', () => {
            const a = preCymbalGroupKey(stackEvent('foo'))
            const b = preCymbalGroupKey(stackEvent('foo', 'different'))

            expect(a).toBe(b)
        })

        it('separates different stacks', () => {
            expect(preCymbalGroupKey(stackEvent('foo'))).not.toBe(preCymbalGroupKey(stackEvent('bar')))
        })

        it('does not conflate adjacent empty fields across frame boundaries', () => {
            const split = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [
                            { function: 'a', filename: 'bc' },
                            { function: '', filename: '' },
                        ],
                    },
                })
            )
            const merged = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [{ function: 'a', filename: 'bc' }],
                    },
                })
            )

            expect(split).not.toBe(merged)
        })

        it('uses abs_path, line, and column aliases', () => {
            const withAliases = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [{ function: 'fn', abs_path: '/app/x.js', line: 10, column: 2 }],
                    },
                })
            )
            const withCanonical = preCymbalGroupKey(
                exceptionEvent({
                    type: 'Error',
                    stacktrace: {
                        frames: [{ function: 'fn', filename: '/app/x.js', lineno: 10, colno: 2 }],
                    },
                })
            )

            expect(withAliases).toBe(withCanonical)
        })

        it('ignores extra frame properties', () => {
            const minimal = preCymbalGroupKey(stackEvent('fn'))
            const verbose = preCymbalGroupKey(
                exceptionEvent({
                    type: 'TypeError',
                    value: 'msg',
                    stacktrace: {
                        frames: [
                            {
                                function: 'fn',
                                filename: 'fn.js',
                                lineno: 1,
                                context_line: 'const x = 1',
                                vars: { x: 1 },
                            },
                        ],
                    },
                })
            )

            expect(minimal).toBe(verbose)
        })
    })
})
